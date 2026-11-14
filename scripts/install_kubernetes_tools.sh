#!/usr/bin/env bash
# Install pinned kind and kubectl binaries into /usr/local/bin after verifying their checksums.
set -euo pipefail

KIND_VERSION="v0.32.0"
KUBECTL_VERSION="v1.36.1"
download_directory=$(mktemp -d)
trap 'rm -rf "${download_directory}"' EXIT
cd "${download_directory}"

curl -fsSLo kind "https://kind.sigs.k8s.io/dl/${KIND_VERSION}/kind-linux-amd64"
curl -fsSLo kind.sha256sum "https://kind.sigs.k8s.io/dl/${KIND_VERSION}/kind-linux-amd64.sha256sum"
echo "$(cut -d ' ' -f 1 kind.sha256sum)  kind" | sha256sum --check

curl -fsSLo kubectl "https://dl.k8s.io/release/${KUBECTL_VERSION}/bin/linux/amd64/kubectl"
curl -fsSLo kubectl.sha256 "https://dl.k8s.io/release/${KUBECTL_VERSION}/bin/linux/amd64/kubectl.sha256"
echo "$(cat kubectl.sha256)  kubectl" | sha256sum --check

sudo install -m 0755 kind /usr/local/bin/kind
sudo install -m 0755 kubectl /usr/local/bin/kubectl
kind version
kubectl version --client
