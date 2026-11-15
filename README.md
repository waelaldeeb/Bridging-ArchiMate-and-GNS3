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

## Running the Experiments

### 1. Install Python dependencies

From the repository's main directory, run:

```bash
pip install -r requirements.txt
```

### 2. Generate a GNS3 topology

Start the GNS3 server and ensure the required device templates are installed.

Run the transformation script using the ArchiMate XML model:

```bash
python src/A2G_52_validated.py --xml "models/A2G-52 nodes(8).xml"
```

For a predeployment check without creating a GNS3 project:

```bash
python src/A2G_52_validated.py --xml "models/A2G-52 nodes(8).xml" --dry-run
```

The default GNS3 server address is `http://localhost:3080`. Full topology generation requires locally available GNS3 templates and compatible device images.

### 3. Verify structural correspondence

Use the independent verification script to compare the ArchiMate XML source with the generated GNS3 project definition.

```bash
python validation/independent_topology_verifier.py "models/A2G-52 nodes(8).xml" "gns3/A2G_AutoGen_20260928_005801/A2G_AutoGen_20260928_005801.gns3" --out "results/verification_recheck.json"
```

Refer to the script's supported command-line arguments and supply the paths to the ArchiMate XML and corresponding `.gns3` file.

### 4. Execute negative-input tests

```bash
python validation/test_a2g_negative_inputs.py
```

The tests cover nonexistent relationship endpoints, insufficient switch-port capacity, and unavailable device templates.

### 5. Review the experimental results

The `results/` directory contains the independent structural-verification report and the negative-input test results in JSON format.

These tests assess source-model validity and structural topology correspondence. They do not establish correctness of runtime device configurations or security-policy enforcement.

## Reproduction Limitations

Reproduction of GNS3 topology generation depends on the locally installed device templates, virtual-machine images, and GNS3 environment. The updated parser's additional input-validation checks have been evaluated offline; full live GNS3 generation using the updated version remains to be confirmed.
