# ParallelCluster Diagnostics

A collection of scripts to diagnose common ParallelCluster issues.
The diagnostics suite is meant to be executed within the cluster head node.

## Requirements

The following tools must be installed on your **local machine** to deploy the diagnostsics suite to your cluster.

| Tool | Purpose |
|---|---|
| `pcluster` | AWS ParallelCluster CLI, used to retrieve head node connection info |
| `ssh` | Used to connect to the head node and install dependencies |
| `rsync` | Used to upload the diagnostics folder to the head node |

## Available Scripts

| Script | Description |
|---|---|
| `diagnose-slurm-accounting.py` | Diagnoses SLURM accounting setup |

## Usage

### 1. Deploy to the head node

Run `deploy.sh` from your local machine. It uploads the diagnostics folder to the head node and installs dependencies.

```bash
bash deploy.sh --cluster-name <cluster-name> --region <region> --ssh-key <path-to-key>
```

At the end it prints the SSH command to log directly into the diagnostics folder on the head node.

### 2. Run a diagnostic script (example)

Once logged into the head node:

```bash
./diagnose-slurm-accounting.py --help
```
