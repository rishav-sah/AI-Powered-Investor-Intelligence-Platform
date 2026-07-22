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

# Step 0: Provision Azure Resources (ACR & AKS)

One-time setup via the Azure Portal, done before Step 1. Skip if the registry/cluster already exist.

## Create Azure Container Registry

1. Azure Portal → Create a resource → search "Container Registry" → select it → Create
2. Select the existing resource group (`rg-inv-intelligence`)
3. Registry name: `invinteligence`
4. Role assignment mode: whatever you pick here has real consequences later see the Known Issue under Step 6 before choosing "RBAC Registry + ABAC Repository Permissions"
5. Next → Next → Create

## Create AKS Cluster

1. Azure Portal → Create a resource → search "Kubernetes Service" → select **Azure Kubernetes Service (AKS)** → Create
2. Select the existing resource group, give the cluster a name, keep the rest of Basics default
3. Node Pools tab: delete the default agent pool (2–5 nodes / 110 pods is more capacity than this project needs) → Add node pool:
   * Node pool type: Virtual machine scale set
   * Node pool name: `invintnode`, Mode: System, OS type: Linux (Ubuntu)
   * Availability zones: deselect all
   * Scale method: Manual, Node count: 2
4. Review + Create

## Bug: node pool VM size rejected — cost me half a day

Creating the cluster in `eastus`, the Node Pools tab rejected the default system node pool size (`Standard_DC2ads_v5`, 2 nodes) with:

```text
4 vCPUs are needed for this configuration, but only 0 vCPUs (of 0) remain for the standardDCADSv5Family.
Request a quota increase.
```

Switching regions in the wizard didn't help. Manually picking other common sizes (`Standard_D2s_v3`) also failed, showing a generic "not available" state in the size picker with no reason given. The obvious next move the wizard's "Request a quota increase" link was a dead end: **Azure for Students subscriptions cannot request quota increases at all**, confirmed via Microsoft's own docs.

**How I found the root cause:**

1. Read the error literally first, it names `standardDCADSv5Family` at `0 vCPUs (of 0)`. Checked regional usage:
   ```bash
   az vm list-usage --location eastus --output table
   ```
   Total regional vCPUs showed `0/6` i.e. headroom exists overall but the specific confidential-compute family (`DCADSv5`) was `0/0`: a hard zero, disabled outright, not exhausted. So the message was technically accurate but misleading about the fix.
2. From that same output, noted other families with nonzero quota (Dv2, Dv3, Dv4, Ev3, F-series, etc.) as replacement candidates.
3. Tried `Standard_D2s_v3` in the wizard picker just said "not available," no reason given.
4. Suspected a subscription policy blocking VM SKUs, checked `az policy assignment list`. Found only a region-allowlist policy, no SKU allowlist. Ruled out policy.
5. Checked whether `D2s_v3` even exists as an offered size in `eastus` `az vm list-sizes --location eastus`. It does. Ruled out "SKU retired from region."
6. Queried the SKU's actual restriction reason directly, this is the command that actually mattered, and the one none of the portal UI or quota views surface:
   ```bash
   az vm list-skus --location eastus --size Standard_D2s_v3 --all --output table
   ```
   The `Restrictions` field showed `NotAvailableForSubscription` at both `Location` and `Zone` level a hard block specific to this subscription, completely invisible from the quota view or a plain size listing.
7. Pulled the full SKU restriction list for `eastus` and filtered for zero-restriction SKUs: 536 of 1356 unrestricted, but dominated by exotic/enterprise families (confidential compute, M-series, HB-series) not ordinary general-purpose sizes.
8. Cross-checked a list of common general-purpose SKUs (`D2_v3`, `D2s_v4`, `D2as_v4`, `F2s`, `B2s_v2`, `G1`, etc.) against `eastus`, all blocked. Confirmed the region itself, not the SKU choice, was the real constraint.
9. Repeated the same check against `canadacentral` (one of this subscription's allowed regions),`D2_v3`, `D2_v4`, `D2s_v4`, `D2as_v4`, `D2ds_v4`, `D2d_v4`, `E2_v3`, and `B2s_v2` all came back unblocked.

**Fix:** changed the cluster's region from East US to **Canada Central**, and the node pool's VM size to **`Standard_D2s_v4`** (2 nodes × 2 vCPUs = 4, within the 6 vCPU regional cap; current non-deprecated generation). Cluster deployed successfully.

**Takeaway:** on Azure for Students, a vCPU quota error can be misleading, there are two independent layers, and the portal error only ever describes one of them.

| Layer | What it means | How to check |
|---|---|---|
| **Quota** (`az vm list-usage`) | How many vCPUs you're allowed to use per family/region | `0/0` = hard-disabled family; `0/N` = available but unused |
| **Subscription-specific SKU restriction** (`az vm list-skus`) | Whether a SKU can be deployed at all in a region, for this subscription type, regardless of quota | Look for `NotAvailableForSubscription` in `Restrictions` |

Quota showing headroom does **not** guarantee a SKU is deployable. When a region shows broad restriction on ordinary SKUs, trying a different allowed region is usually faster than hunting for a workaround SKU in the original one.

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

Known Issues:

* **Running the plain command above crashes on startup:** `.env` is deliberately excluded from the image (`.dockerignore`), so with no env vars passed every `POSTGRES_*` var is unset and `psycopg2` falls back to a local Unix socket that doesn't exist in the container:
  ```text
  psycopg2.OperationalError: connection to server on socket "/var/run/postgresql/.s.PGSQL.5432" failed: No such file or directory
  ```
  Same root cause as Bug 1 in the "Bugs I Encountered" section below, just hit locally first instead of on the AKS pod. Fix — rerun with the env file passed in:
  ```bash
  docker run --env-file .env -p 8000:8000 invint
  ```
* **Still fails after adding `--env-file .env`:**
  ```text
  psycopg2.OperationalError: connection to server at "inv-intelligence...." port 5432 failed: Connection refused
  ```
  The Azure Database for PostgreSQL Flexible Server's networking rules didn't allow the local machine's public IP. Fix in the Portal: Postgres server → Networking → add a firewall rule for your current IP (the quick-add "Allow public access from Azure services and resources within Azure" / current-IP buttons both work), or via CLI:
  ```bash
  az postgres flexible-server firewall-rule create --resource-group rg-inv-intelligence --server-name inv-intelligence --name AllowMyIP --start-ip-address <your-ip> --end-ip-address <your-ip>
  ```
  This is a separate rule from the AKS one added in Bug 2 below — local dev and the AKS cluster connect from different IPs and both need their own firewall entry.

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

## Bug: pushed successfully, but the repository was nowhere to be found

`docker push` completed successfully, but the pushed image wasn't visible anywhere. Azure Portal → ACR → **Repositories** blade said:

```text
You do not have permissions to list the repositories for this registry. Please ensure that you have the
appropriate role assignments to access registry data plane resources.
```

The CLI equivalent from the command above failed the same way:

```text
az acr repository list --name invinteligence --output table
→ Error: authentication required, visit https://aka.ms/acr/authorization for more information.
```

My first instinct was a role/scope problem, so I assigned the classic **AcrPush** role directly on the registry, to the correct user. No effect.

**How I found the root cause:**

1. Confirmed identity/subscription context — `az account show` → correct user and subscription. Not a wrong-login issue.
2. Confirmed the registry exists and is otherwise healthy — `az acr list` → registry found, login server and admin-enabled status confirmed.
3. Confirmed the role assignment was actually there — `az role assignment list --scope <registry-id>` → `AcrPush` was correctly assigned, directly on the registry resource. So it wasn't wrong-scope or wrong-identity.
4. Forced a full credential refresh (`az logout` / `az login` / `az acr login`) to rule out a stale AAD token. `az acr login` itself succeeded (the Docker token exchange worked), but `az acr repository list` still failed — which told me the two auth paths behave differently, so the token wasn't the problem.
5. Checked the registry's role assignment mode directly:
   ```bash
   az acr show --name invinteligence --query "roleAssignmentMode"
   ```
   This was the turning point — it came back `AbacRepositoryPermissions`. I'd picked "RBAC Registry + ABAC Repository Permissions" during creation in Step 0 without realizing the consequence: in this mode, the legacy `AcrPull`/`AcrPush`/`AcrDelete` roles are **not honored at all**, no matter how correctly they're scoped.
   With ABAC mode, pull/push instead needs the **Container Registry Repository Reader/Writer/Contributor** roles. I assigned `Container Registry Repository Writer` and retested — still failed.
6. Reran with `--debug` to see the raw HTTP response instead of the CLI's generic error message. That surfaced the real detail:
   ```text
   Www-Authenticate: Bearer ... scope="registry:catalog:*", error="insufficient_scope"
   ```
   This isolated the problem to specifically the **catalog listing** action — separate from pull/push, which were actually fine.
7. That pointed to the one role that grants `registry:catalog:*`: **Container Registry Repository Catalog Lister**.

**Fix:**

```bash
az role assignment create --assignee <your-azure-account-email> --role "Container Registry Repository Catalog Lister" \
  --scope /subscriptions/<subscription-id>/resourceGroups/rg-inv-intelligence/providers/Microsoft.ContainerRegistry/registries/invinteligence

az acr login --name invinteligence
az acr repository list --name invinteligence --output table
```

That resolved it. Takeaway for any ABAC-mode registry (`roleAssignmentMode: AbacRepositoryPermissions`): three separate role families exist for three separate purposes, and none of them substitute for another —

| Need | Role |
|---|---|
| Manage the registry resource itself | Owner / Contributor / Reader (control plane only in ABAC mode) |
| Pull / push / delete image data | Container Registry Repository Reader / Writer / Contributor |
| List all repositories (catalog) | Container Registry Repository Catalog Lister |

The original `AcrPush` role assignment is dead weight once on ABAC mode — not honored, but harmless. Worth removing so it doesn't confuse a future audit:

```bash
az role assignment delete --assignee <your-azure-account-email> --role "AcrPush" \
  --scope /subscriptions/<subscription-id>/resourceGroups/rg-inv-intelligence/providers/Microsoft.ContainerRegistry/registries/invinteligence
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

After fixing Bug 1 and letting the rollout restart, the pod showed `Running` / `1/1` (there's no readiness probe defined, so Kubernetes marks it ready as soon as the process starts but that doesn't mean the app is actually up), but the logs never moved past:

```text
INFO:     Waiting for application startup.
```

No error, no crash, no timeout for several minutes just silence. A hang like that (instead of a fast auth/connection-refused error) usually means the TCP handshake itself is being dropped, not rejected at the app layer. I checked the Azure PostgreSQL flexible server's firewall:

```bash
az postgres flexible-server firewall-rule list --resource-group rg-inv-intelligence --server-name inv-intelligence -o table
```

It only allow-listed two old IPs from local development not AKS's outbound IP. I found the cluster's real outbound IP and opened it up:

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
* Managed Identity for ACR/AKS authentication instead of the password-based admin credentials used in Step 4/9 — this deployment uses admin username/password for simplicity, but production setups typically create a managed identity and grant access through it instead
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
