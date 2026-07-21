# Azure AKS Deployment Guide - AI Powered Investor Intelligence Platform

## Overview

This document explains how to deploy the application from a local machine to Azure Kubernetes Service (AKS).

Deployment Flow:

```text
Local Application
    ↓
Docker Image
    ↓
Azure Container Registry (ACR)
    ↓
Azure Kubernetes Service (AKS)
    ↓
Azure PostgreSQL
    ↓
Public Load Balancer
    ↓
Application URL
```

---

# Step 1: Build Docker Image

Build the Docker image locally.

```bash
docker build -t invint .
```

Verify image creation.

```bash
docker images
```

Expected Output:

```text
REPOSITORY    TAG
invint        latest
```

---

# Step 2: Run Docker Locally

Run the container locally.

```bash
docker run -p 8000:8000 invint
```

Open browser:

```text
http://localhost:8000
```

Verify:

* Application loads successfully
* Dashboard renders
* PDF upload works
* Chatbot works

Stop container:

```bash
Ctrl + C
```

---

# Step 3: Login to Azure

Authenticate with Azure.

```bash
az login
```

Verify subscription.

```bash
az account show
```

---

# Step 4: Login to Azure Container Registry (ACR)

Login using Azure CLI.

```bash
az acr login --name invinteligence
```

Alternative login using username/password.

Retrieve credentials.

```bash
az acr credential show --name invinteligence
```

Login manually.

```bash
docker login invinteligence.azurecr.io
```

Provide:

```text
Username: invinteligence
Password: <acr-password>
```

Expected Output:

```text
Login Succeeded
```

---

# Step 5: Tag Docker Image

Tag local image for ACR.

```bash
docker tag invint:latest invinteligence.azurecr.io/invint:v1
```

Verify image.

```bash
docker images
```

Expected Output:

```text
invinteligence.azurecr.io/invint    v1
```

---

# Step 6: Push Docker Image to ACR

Push image.

```bash
docker push invinteligence.azurecr.io/invint:v1
```

Verify image push.

```bash
az acr repository list --name invinteligence --output table
```

---

# Step 7: Connect to AKS

Download cluster credentials.

```bash
az aks get-credentials --resource-group rg-inv-intelligence --name inv-intelligence-cluster --overwrite-existing
```

Verify connection.

```bash
kubectl get nodes
```

Expected Output:

```text
STATUS
Ready
```

---

# Step 8: Verify AKS Can Access ACR

Attach ACR to AKS.

```bash
az aks update --resource-group rg-inv-intelligence --name inv-intelligence-cluster --attach-acr invinteligence
```

Verify access.

```bash
az aks check-acr --resource-group rg-inv-intelligence --name inv-intelligence-cluster --acr invinteligence
```

Expected Output:

```text
Your cluster can pull images from invinteligence.azurecr.io!
```


---

# Step 9: Create Image Pull Secret

If AKS cannot pull images directly from ACR, create a Docker Registry Secret.

Retrieve ACR credentials.

```bash
az acr credential show --name invinteligence
```

Create secret.

```bash
kubectl create secret docker-registry acr-secret \
  --docker-server=invinteligence.azurecr.io \
  --docker-username=invinteligence \
  --docker-password=<acr-password>
```

Configure default service account to use the secret.

```bash
kubectl patch serviceaccount default -p "{\"imagePullSecrets\": [{\"name\": \"acr-secret\"}]}"
```

---

# Step 10: Deploy Application

Create deployment.

```bash
kubectl create deployment invint --image=invinteligence.azurecr.io/invint:v1
```

Verify deployment.

```bash
kubectl get deployments
```

Expected Output:

```text
NAME     READY
invint   1/1
```

---

# Step 11: Monitor Pod Startup

List pods.

```bash
kubectl get pods
```

Watch pod startup.

```bash
kubectl get pods -w
```

Expected Output:

```text
STATUS
Running
```

---

# Step 12: View Application Logs

Current logs.

```bash
kubectl logs <pod-name>
```

Example:

```bash
kubectl logs invint-xxxxxxxxxx-yyyyy
```

Follow logs in real time.

```bash
kubectl logs -f <pod-name>
```

View previous container logs.

```bash
kubectl logs <pod-name> --previous
```

Describe pod.

```bash
kubectl describe pod <pod-name>
```

---

# Bugs I Encountered During Deployment

## Bug 1: Pod crashed on startup — Postgres connection failing over a local socket

After Step 10, `kubectl logs <pod-name>` showed the app crash immediately on startup:

```text
psycopg2.OperationalError: connection to server on socket "/var/run/postgresql/.s.PGSQL.5432" failed: No such file or directory
Failed to create database: connection to server on socket "/var/run/postgresql/.s.PGSQL.5432" failed: No such file or directory
```

`kubectl create deployment` doesn't set any environment variables on the pod. My app reads `POSTGRES_HOST`, `POSTGRES_PORT`, `POSTGRES_USER`, `POSTGRES_PASSWORD`, `POSTGRES_DATABASE` (plus the Azure OpenAI/Search keys) from the environment via `os.getenv(...)`, and `.env` is deliberately excluded from the Docker image (see `.dockerignore`), so none of it was set. With `POSTGRES_HOST` empty, `psycopg2` fell back to a local Unix socket that doesn't exist inside the container.

I fixed it by creating a Secret from my local `.env` and injecting it into the deployment:

```bash
kubectl create secret generic app-env --from-env-file=.env
kubectl set env deployment/invint --from=secret/app-env
```

## Bug 2: Pod stuck at "Waiting for application startup" forever, no error

After fixing Bug 1 and letting the rollout restart, the pod showed `Running` / `1/1` (there's no readiness probe defined, so Kubernetes marks it ready as soon as the process starts — that doesn't mean the app is actually up), but the logs never moved past:

```text
INFO:     Waiting for application startup.
```

No error, no crash, no timeout for several minutes — just silence. A hang like that (instead of a fast auth/connection-refused error) usually means the TCP handshake itself is being dropped, not rejected at the app layer. I checked the Azure PostgreSQL flexible server's firewall:

```bash
az postgres flexible-server firewall-rule list --resource-group rg-inv-intelligence --server-name inv-intelligence -o table
```

It only allow-listed two old IPs from local development — not AKS's outbound IP. I found the cluster's real outbound IP and opened it up:

```bash
az aks show --resource-group rg-inv-intelligence --name inv-intelligence-cluster --query "networkProfile.loadBalancerProfile.effectiveOutboundIPs[0].id" -o tsv

az network public-ip show --ids <id from above> --query ipAddress -o tsv

az postgres flexible-server firewall-rule create \
  --resource-group rg-inv-intelligence \
  --server-name inv-intelligence \
  --name AllowAKSCluster \
  --start-ip-address <aks-outbound-ip> \
  --end-ip-address <aks-outbound-ip>
```

Then restarted the rollout and confirmed:

```bash
kubectl rollout restart deployment/invint
kubectl rollout status deployment/invint
kubectl logs <new-pod-name> --tail=10
```

```text
INFO:     Application startup complete.
INFO:     Uvicorn running on http://0.0.0.0:8000
```

---

# Step 13: Expose Application

Create public Load Balancer.

```bash
kubectl expose deployment invint --type=LoadBalancer --port=80 --target-port=8000
```

Verify service.

```bash
kubectl get svc
```

Expected Output:

```text
NAME     TYPE           EXTERNAL-IP
invint   LoadBalancer   20.xxx.xxx.xxx
```

---

# Step 14: Access Application

Open browser.

```text
http://<external-ip>
```

Example:

```text
http://20.xxx.xxx.xxx
```

---

# Common Troubleshooting Commands

List Nodes

```bash
kubectl get nodes
```

List Pods

```bash
kubectl get pods
```

List Services

```bash
kubectl get svc
```

List Deployments

```bash
kubectl get deployments
```

Describe Deployment

```bash
kubectl describe deployment invint
```

Describe Pod

```bash
kubectl describe pod <pod-name>
```

View Logs

```bash
kubectl logs <pod-name>
```

Follow Logs

```bash
kubectl logs -f <pod-name>
```

Restart Deployment

```bash
kubectl rollout restart deployment invint
```

Delete Deployment

```bash
kubectl delete deployment invint
```

Delete Service

```bash
kubectl delete service invint
```

Delete Secret

```bash
kubectl delete secret acr-secret
```

Delete All Resources

```bash
kubectl delete all --all
```

---

# AKS Cluster Operations

List AKS Clusters

```bash
az aks list --output table
```

Get AKS Credentials

```bash
az aks get-credentials --resource-group rg-inv-intelligence --name inv-intelligence-cluster --overwrite-existing
```

Delete AKS Cluster

```bash
az aks delete --resource-group rg-inv-intelligence --name inv-intelligence-cluster --yes --no-wait
```

Verify Deletion

```bash
az aks list --output table
```

---

# ACR Operations

List Registries

```bash
az acr list --output table
```

Show Registry Details

```bash
az acr show --name invinteligence
```

Show Registry Credentials

```bash
az acr credential show --name invinteligence
```

Delete Registry

```bash
az acr delete --name invinteligence --resource-group rg-inv-intelligence --yes
```

---

# Production Enhancements

The current deployment is functional and suitable for demonstrations and development purposes.

Typical production enhancements include:

* GitHub Actions CI/CD
* Azure Key Vault Integration
* HTTPS / SSL Certificates
* Custom Domain
* NGINX Ingress Controller
* Monitoring and Logging
* Horizontal Pod Autoscaling
* Application Authentication
* Private Networking
* WAF Protection

These enhancements can be implemented incrementally as part of future deployment improvements.
