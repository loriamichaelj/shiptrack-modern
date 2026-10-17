"""The GCP side of the cloud ports (ADR-0032).

Credentials are Application Default Credentials, which on GKE resolve through Workload Identity
Federation. Nothing here reads a key file, and no setting names one.
"""
