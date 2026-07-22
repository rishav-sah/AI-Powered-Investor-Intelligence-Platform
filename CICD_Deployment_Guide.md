# AKS CI/CD Deployment Reference Guide

This document explains every field used in the following files:

```text
k8s/deployment.yaml
k8s/service.yaml
.github/workflows/deploy.yaml
```

The goal is to understand not only what each field does, but also why we are using it in our Investor Intelligence Platform project.

---

# deployment.yaml

## Complete File

```yaml
apiVersion: apps/v1
kind: Deployment

metadata:
  name: invint

spec:
  replicas: 1

  selector:
    matchLabels:
      app: invint

  template:
    metadata:
      labels:
        app: invint

    spec:
      containers:
      - name: invint

        image: invinteligence.azurecr.io/invint:latest

        imagePullPolicy: Always

        envFrom:
        - secretRef:
            name: invint-secrets

        ports:
        - containerPort: 8000
```

---

## apiVersion

```yaml
apiVersion: apps/v1
```

This tells Kubernetes which API group should process this resource. Deployments belong to the `apps/v1` API group. Whenever Kubernetes reads this file, it knows that this resource should be handled by the Deployment controller.

---

## kind

```yaml
kind: Deployment
```

This tells Kubernetes what resource to create.

In Kubernetes, everything is represented as a resource.

Examples:

```text
Deployment
Service
Secret
ConfigMap
Ingress
```

In our case we want Kubernetes to create and manage application pods, therefore we use a Deployment resource.

---

## metadata

```yaml
metadata:
  name: invint
```

This is the unique name of the deployment inside the cluster.

We use this name later when checking deployment status, restarting deployments, viewing logs, and troubleshooting.

Examples:

```bash
kubectl get deployment invint
kubectl rollout restart deployment/invint
kubectl describe deployment invint
```

Think of this as the identifier for our application deployment.

---

## replicas

```yaml
replicas: 1
```

This defines how many copies of the application should be running.

For our project we use:

```yaml
replicas: 1
```

to reduce Azure costs while demonstrating the deployment process.

In production systems this is usually increased.

Example:

```yaml
replicas: 3
```

This would create three identical application pods.

If one pod crashes, the remaining pods continue serving users.

---

## selector

```yaml
selector:
  matchLabels:
    app: invint
```

The deployment needs a way to identify which pods belong to it.

The selector tells Kubernetes:

```text
Manage all pods having app=invint
```

This creates the relationship between the deployment and its pods.

The selector must match the labels defined inside the pod template.

---

## template

```yaml
template:
```

The template section acts as the blueprint used to create pods.

Whenever Kubernetes needs to create a new pod, it uses the configuration defined inside this section.

Think of this as a manufacturing template.

Every pod created by the deployment will follow this template.

---

## labels

```yaml
labels:
  app: invint
```

Labels are tags attached to Kubernetes resources.

Here we are assigning:

```text
app=invint
```

to all application pods.

These labels are later used by:

```text
Deployments
Services
Monitoring Tools
Ingress Controllers
```

to identify resources.

---

## container name

```yaml
name: invint
```

This defines the container name inside the pod.

This name is mainly used for:

```text
Logging
Debugging
Monitoring
Container Identification
```

When multiple containers exist inside a pod, this name becomes important.

---

## image

```yaml
image: invinteligence.azurecr.io/invint:latest
```

This tells Kubernetes where the application image is stored.

Breakdown:

```text
Registry    : invinteligence.azurecr.io
Repository  : invint
Tag         : latest
```

When a pod starts, AKS downloads this image from Azure Container Registry.

This image contains:

```text
Application Code
Python Runtime
Dependencies
Libraries
```

Everything required to run the application.

---

## containerPort

```yaml
containerPort: 8000
```

This tells Kubernetes that the FastAPI application is listening on port 8000 inside the container.

This port is internal to the container.

Users will never directly access this port.

Instead:

```text
Load Balancer
↓
Service
↓
Container Port 8000
```

---

## imagePullPolicy

```yaml
imagePullPolicy: Always
```

This instructs Kubernetes to always check ACR for the latest image before starting a pod.

This is useful during CI/CD because every deployment automatically pulls the newest image.

Without this, Kubernetes may reuse an older cached image.

---

## envFrom

```yaml
envFrom:
- secretRef:
    name: invint-secrets
```

This injects every key in the `invint-secrets` Kubernetes Secret into the container as an environment variable, without listing each one individually in this file.

`invint-secrets` isn't checked into this manifest — the workflow's **Create Kubernetes Secrets** step (see the `deploy.yaml` section below) creates or updates it on every run from the GitHub Actions repository secrets, right before this file is applied.

Without this field, the app's `os.getenv(...)` calls (Postgres, Azure OpenAI, Azure AI Search config) would all return `None` and the app would crash on startup.

---

# service.yaml

## Complete File

```yaml
apiVersion: v1
kind: Service

metadata:
  name: invint

spec:
  selector:
    app: invint

  type: LoadBalancer

  ports:
  - protocol: TCP
    port: 80
    targetPort: 8000
```

---

## apiVersion

```yaml
apiVersion: v1
```

Services belong to the Kubernetes Core API group, which uses `v1`.

This tells Kubernetes which API should handle the Service resource.

---

## kind

```yaml
kind: Service
```

Creates a networking layer for our application.

Without a Service:

```text
Pods Exist
Application Exists
Users Cannot Access It
```

The Service acts as the bridge between users and application pods.

---

## metadata

```yaml
metadata:
  name: invint
```

This becomes the name of the Service.

Useful commands:

```bash
kubectl get svc
kubectl describe svc invint
```

---

## selector

```yaml
selector:
  app: invint
```

The Service must know which pods should receive traffic.

This selector tells Kubernetes:

```text
Forward traffic to pods having app=invint
```

Since our deployment creates pods with:

```yaml
labels:
  app: invint
```

the Service can automatically discover them.

---

## type

```yaml
type: LoadBalancer
```

This is one of the most important settings.

Azure automatically creates:

```text
Public IP
Azure Load Balancer
```

when this type is used.

Without LoadBalancer:

```text
Application Remains Internal
```

With LoadBalancer:

```text
Internet Users Can Access Application
```

---

## protocol

```yaml
protocol: TCP
```

Specifies the network protocol used for communication.

Web applications typically use:

```text
TCP
```

because HTTP and HTTPS are built on top of TCP.

---

## port

```yaml
port: 80
```

This is the public port exposed to users.

Users access:

```text
http://<public-ip>
```

which automatically uses port 80.

---

## targetPort

```yaml
targetPort: 8000
```

The Service forwards incoming traffic to the FastAPI application running on container port 8000.

Traffic flow:

```text
User
 ↓
Public IP
 ↓
Port 80
 ↓
Service
 ↓
Port 8000
 ↓
FastAPI Application
```

---

# deploy.yaml

## Complete File

```yaml
name: Build and Deploy to AKS

on:
  push:
    branches:
      - main

jobs:

  build-and-deploy:

    runs-on: ubuntu-latest

    steps:

      - name: Checkout Repository
        uses: actions/checkout@v4

      - name: Docker Login to ACR
        run: |
          docker login ${{ secrets.ACR_LOGIN_SERVER }} \
            -u ${{ secrets.ACR_USERNAME }} \
            -p ${{ secrets.ACR_PASSWORD }}

      - name: Build Docker Image
        run: |
          docker build \
            -t ${{ secrets.ACR_LOGIN_SERVER }}/invint:latest .

      - name: Push Docker Image
        run: |
          docker push \
            ${{ secrets.ACR_LOGIN_SERVER }}/invint:latest

      - name: Configure kubectl
        run: |
          echo "${{ secrets.AKS_CA_CERT }}" | base64 -d > ${{ runner.temp }}/ca.crt
          kubectl config set-cluster aks-cluster \
            --server="${{ secrets.AKS_API_SERVER }}" \
            --certificate-authority=${{ runner.temp }}/ca.crt \
            --embed-certs=true
          kubectl config set-credentials github-actions-deployer \
            --token="${{ secrets.AKS_SA_TOKEN }}"
          kubectl config set-context aks-context \
            --cluster=aks-cluster \
            --user=github-actions-deployer \
            --namespace=default
          kubectl config use-context aks-context

      - name: Create Kubernetes Secrets
        run: |
          kubectl create secret generic invint-secrets \
            --from-literal=AZURE_OPENAI_ENDPOINT="${{ secrets.AZURE_OPENAI_ENDPOINT }}" \
            --from-literal=AZURE_OPENAI_CHAT_ENDPOINT="${{ secrets.AZURE_OPENAI_CHAT_ENDPOINT }}" \
            --from-literal=AZURE_OPENAI_API_KEY="${{ secrets.AZURE_OPENAI_API_KEY }}" \
            --from-literal=AZURE_OPENAI_API_EMBEDDING_VERSION="${{ secrets.AZURE_OPENAI_API_EMBEDDING_VERSION }}" \
            --from-literal=AZURE_OPENAI_API_VERSION="${{ secrets.AZURE_OPENAI_API_VERSION }}" \
            --from-literal=AZURE_SEARCH_ENDPOINT="${{ secrets.AZURE_SEARCH_ENDPOINT }}" \
            --from-literal=AZURE_SEARCH_API_KEY="${{ secrets.AZURE_SEARCH_API_KEY }}" \
            --from-literal=AZURE_SEARCH_INDEX_NAME="${{ secrets.AZURE_SEARCH_INDEX_NAME }}" \
            --from-literal=AZURE_OPENAI_EMBEDDING_DEPLOYMENT="${{ secrets.AZURE_OPENAI_EMBEDDING_DEPLOYMENT }}" \
            --from-literal=AZURE_OPENAI_CHAT_DEPLOYMENT="${{ secrets.AZURE_OPENAI_CHAT_DEPLOYMENT }}" \
            --from-literal=POSTGRES_HOST="${{ secrets.POSTGRES_HOST }}" \
            --from-literal=POSTGRES_PORT="${{ secrets.POSTGRES_PORT }}" \
            --from-literal=POSTGRES_DATABASE="${{ secrets.POSTGRES_DATABASE }}" \
            --from-literal=POSTGRES_USER="${{ secrets.POSTGRES_USER }}" \
            --from-literal=POSTGRES_PASSWORD="${{ secrets.POSTGRES_PASSWORD }}" \
            --dry-run=client -o yaml | kubectl apply -f -

      - name: Deploy Application
        run: |
          kubectl apply -f k8s/deployment.yaml
          kubectl apply -f k8s/service.yaml

      - name: Restart Deployment
        run: |
          kubectl rollout restart deployment/invint

      - name: Verify Rollout
        run: |
          kubectl rollout status deployment/invint
```

---

## Workflow Name

```yaml
name: Build and Deploy to AKS
```

The name displayed inside GitHub Actions.

This helps identify the workflow in the Actions dashboard.

---

## Trigger

```yaml
on:
  push:
    branches:
      - main
```

This tells GitHub when to execute the pipeline.

Whenever code is pushed to:

```text
main
```

the workflow automatically starts.

---

## runs-on

```yaml
runs-on: ubuntu-latest
```

GitHub creates a temporary Ubuntu virtual machine to execute all pipeline steps.

Think of this as a temporary build server.

---

## Checkout Repository

```yaml
uses: actions/checkout@v4
```

Downloads the source code into the GitHub runner.

Without this step:

```text
Dockerfile Not Available
Source Code Not Available
Build Fails
```

---

## Docker Login to ACR

```yaml
docker login ${{ secrets.ACR_LOGIN_SERVER }} \
  -u ${{ secrets.ACR_USERNAME }} \
  -p ${{ secrets.ACR_PASSWORD }}
```

Authenticates Docker against Azure Container Registry using the registry's built-in admin account, instead of an Azure AD identity.

Without this step:

```text
Docker Push Fails
Unauthorized Error
```

Why not `azure/login` + `az acr login` (an Azure AD service principal)? This project's Azure subscription lives inside FIU's Azure AD tenant, which has application registration turned off for regular accounts — `az ad sp create-for-rbac` fails with `Insufficient privileges to complete the operation`, so there's no way to mint the client-ID/client-secret pair that `azure/login` needs. Authenticating with the ACR's own admin username/password (`az acr credential show --name invinteligence`) sidesteps Azure AD entirely and needs no directory permissions at all.

---

## Build Docker Image

```yaml
docker build
```

Creates a Docker image from:

```text
Dockerfile
Source Code
Requirements
Dependencies
```

This produces a deployable container image.

---

## Push Docker Image

```yaml
docker push
```

Uploads the Docker image to Azure Container Registry.

After this step:

```text
AKS Can Pull The Image
```

---

## Configure kubectl

```yaml
echo "${{ secrets.AKS_CA_CERT }}" | base64 -d > ${{ runner.temp }}/ca.crt
kubectl config set-cluster aks-cluster \
  --server="${{ secrets.AKS_API_SERVER }}" \
  --certificate-authority=${{ runner.temp }}/ca.crt \
  --embed-certs=true
kubectl config set-credentials github-actions-deployer \
  --token="${{ secrets.AKS_SA_TOKEN }}"
kubectl config set-context aks-context \
  --cluster=aks-cluster \
  --user=github-actions-deployer \
  --namespace=default
kubectl config use-context aks-context
```

Connects `kubectl` to the AKS cluster, replacing what `az aks get-credentials` would normally do.

Same root cause as the ACR login above: `az aks get-credentials` needs an authenticated `az` session, which needs `azure/login`, which needs the Azure AD service principal this tenant won't let us create. So instead of authenticating as an Azure identity, the pipeline authenticates as a **Kubernetes-native identity** — a `ServiceAccount` created directly inside the cluster:

```bash
kubectl create serviceaccount github-actions-deployer -n default
```

with a `Role` + `RoleBinding` scoping it to only `deployments`, `replicasets`, `services`, `secrets`, and `pods` inside the `default` namespace (not full cluster-admin), and a long-lived token pulled from a manually-created `kubernetes.io/service-account-token` Secret bound to that ServiceAccount.

Three secrets carry what's needed to build a kubeconfig context from scratch, entirely inside the job:

```text
AKS_API_SERVER  : the cluster's API server URL
AKS_CA_CERT     : the cluster's CA certificate, base64-encoded
AKS_SA_TOKEN    : the ServiceAccount's bearer token
```

Without this step:

```text
kubectl Cannot Access AKS
```

---

## Create Kubernetes Secrets

```yaml
kubectl create secret generic invint-secrets \
  --from-literal=AZURE_OPENAI_ENDPOINT="${{ secrets.AZURE_OPENAI_ENDPOINT }}" \
  ...
  --dry-run=client -o yaml | kubectl apply -f -
```

Builds (or updates) the `invint-secrets` Kubernetes Secret that `k8s/deployment.yaml`'s `envFrom` references, from the app-config values stored as GitHub Actions repository secrets (`AZURE_OPENAI_*`, `AZURE_SEARCH_*`, `POSTGRES_*` — the same keys the app reads locally from `.env` via `os.getenv(...)`).

The `--dry-run=client -o yaml | kubectl apply -f -` pattern generates the Secret manifest locally instead of calling the cluster's create API directly, then applies it. This makes the step idempotent — re-running it on every deploy updates the existing Secret in place instead of failing with `AlreadyExists` on the second and subsequent runs.

Without this step:

```text
Pod Starts With No POSTGRES_*/AZURE_*  Env Vars
psycopg2.OperationalError On Startup
```

---

## Deploy Application

```yaml
kubectl apply -f k8s/deployment.yaml
kubectl apply -f k8s/service.yaml
```

Creates the resources if they don't exist.

Updates them if they already exist.

This is why we do not need:

```bash
kubectl create deployment
kubectl expose deployment
```

manually.

---

## Restart Deployment

```yaml
kubectl rollout restart deployment/invint
```

Forces Kubernetes to recreate pods using the latest image from ACR.

This ensures newly pushed images are picked up immediately.

---

## Verify Rollout

```yaml
kubectl rollout status deployment/invint
```

Waits until deployment completes successfully.

This acts as a health check for the deployment process.

If the deployment fails, the GitHub Action also fails.
