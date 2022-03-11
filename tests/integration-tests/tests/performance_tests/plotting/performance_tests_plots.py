import json
from pathlib import Path

import click
import matplotlib.pyplot as plt

from ..common import METRICS


@click.command()
@click.option("--datadir", help="Directory containing the dataset.", required=True, type=click.Path())
@click.option("--outdir", help="Directory where to create plots.", required=True, type=click.Path())
@click.option("--configurations", help="Comma separated list of configurations.", required=True)
@click.option("--nodes", help="Comma separated list of nodes.", required=True)
def generate(datadir, outdir, configurations, nodes):
    generate_plots(datadir, outdir, configurations.split(","), nodes.split(","))


def generate_plots(datadir, outdir, configurations, nodes):
    # Load samples
    samples = {}
    for configuration in configurations:
        samples[configuration] = {}
        for n in nodes:
            samples_file = f"{datadir}/{configuration}/{n}nodes/samples.json"
            with open(samples_file) as f:
                samples[configuration][str(n)] = json.load(f)

    for metric in [metric["name"] for metric in METRICS]:
        data = {}

        # Create Dataset
        for configuration in configurations:
            data[configuration] = [
                [float(v) for v in samples[configuration][str(n)][f"{metric}Sample"].split(",")] for n in nodes
            ]

        # Figure
        fig, ax = plt.subplots(figsize=(10, 5), layout="constrained")

        # Titles
        ax.set_title(f"AWS ParallelCluster\n{metric}", fontweight="bold")
        ax.set_xlabel("Compute Nodes", fontweight="bold")
        ax.set_ylabel(f"Time ({next(m['unit'] for m in METRICS if m['name'] == metric)})", fontweight="bold")

        n_configurations = len(configurations)
        n_nodes = len(nodes)
        all_positions = [i for i in range(1, n_configurations * n_nodes + 1)]

        # Box Plots
        box_plots = {}
        for configuration in configurations:
            positions = all_positions[configurations.index(configuration) :: n_configurations]  # noqa: E203
            box_plots[configuration] = ax.boxplot(
                data[configuration],
                patch_artist=True,
                boxprops=dict(facecolor="palegreen" if configuration == "baseline" else "steelblue"),
                labels=nodes,
                positions=positions,
            )

        # Legend
        boxes = [box_plots[bp]["boxes"][0] for bp in box_plots]
        ax.legend(boxes, configurations, loc="upper left")

        # Plot
        file = Path(f"{outdir}/{metric}.png")
        file.parent.mkdir(parents=True, exist_ok=True)
        plt.savefig(file.absolute())
