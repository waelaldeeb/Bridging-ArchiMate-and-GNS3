# Bridging ArchiMate and GNS3

## Overview

This repository contains the implementation and supporting experimental artifacts for a graph-based, model-driven transformation framework that converts ArchiMate enterprise architecture models into GNS3 network emulation topologies.

The framework extracts eligible network infrastructure elements and physical connectivity relationships from ArchiMate XML, organizes them into an intermediate graph representation, and generates corresponding GNS3 nodes and links.

The implementation also supports source-to-target structural traceability and validation of selected model inputs.

## Repository Contents

- `src/` — Python transformation implementation.
- `models/` — ArchiMate XML models used in the experiments.
- `gns3/` — Generated GNS3 project definitions.
- `validation/` — Independent structural verification and negative-input tests.
- `results/` — Machine-readable verification and test results.
- `archive/` — Earlier implementation artifacts.

## Experimental Evaluation

The evaluation includes a seven-node baseline for topology-construction timing and a 54-node topology containing a NAT component, pfSense firewall, router, three Ethernet switches, and 48 client nodes.

Independent structural verification compares the ArchiMate source model with the generated GNS3 project, including device identities and physical connectivity. Negative-input tests examine missing relationship endpoints, insufficient switch-port capacity, and unavailable GNS3 templates.

## Requirements

- Python 3
- GNS3 2.2.x
- ArchiMate XML export
- Python packages: `requests`, `gns3fy`, and `pydantic<2`
- Appropriate GNS3 device templates and VM images for full topology generation

## Reproducibility

The transformation implementation, input models, generated project definitions, validation scripts, and experimental results are organized into separate directories.

Topology generation requires a running GNS3 environment with compatible templates and images. Structural verification and offline negative-input tests can be executed separately.

The reported fidelity concerns network nodes and physical links. Automatic configuration of IP addresses, routing policies, and firewall rules is outside the implementation scope.

## Research Scope

The principal contribution is architecture-driven network-topology transformation with verifiable source-to-target structural correspondence. Cybersecurity scenarios illustrate the use of the resulting emulation environment but do not imply automatic security-policy enforcement or validation.
