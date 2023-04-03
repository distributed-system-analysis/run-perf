#!/bin/env python3
# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; either version 2 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.
#
# See LICENSE for more details.
#
# Copyright: Red Hat Inc. 2022
# Author: Lukas Doktor <ldoktor@redhat.com>
import argparse
import glob
import json
import os
import sys

HTML1 = """<html>
<script src="https://cdnjs.cloudflare.com/ajax/libs/Chart.js/3.9.1/chart.min.js"></script>
<body>
"""

HTML2 = "</body></html>"

CHART1 = """<div style="width:1200px;height:800px;">
<h3>%s</h3>
<canvas id="%s" width="640" height="400"></canvas>
<script>
const ctx%s = document.getElementById('%s').getContext('2d');
const my%s = new Chart(ctx%s, {
    type: 'line',
    data: {
        datasets: [
"""

CHART2 = """    },
    options: {
        scales: {
            y: {
                beginAtZero: true
            }
        }
    }
});
</script>
</div>
"""

COLORS = ["#{0:02x}0000", "#00{0:02x}00", "#0000{0:02x}", "#{0:02x}{0:02x}00",
          "#{0:02x}00{0:02x}", "#00{0:02x}{0:02x}", "#{0:02x}{0:02x}{0:02x}"]


def parse_args():
    """Argument parser"""
    parser = argparse.ArgumentParser(prog='data_analysis', description='Allows'
                                     'to process multiple pbench results and '
                                     'display all matching iterations in '
                                     'html charts and individual sample values'
                                     ' in CSV format.')
    parser.add_argument("path_glob", help="Glob-like path to main pbench "
                        "dirs to be processed, for example "
                        " '*/TunedLibvirt/fio-rot-*/*' (glob will be used "
                        "internally to find all iterations)")
    parser.add_argument("-o", "--output", help="Output filename (%(default)s)",
                        default="output.html")
    parser.add_argument("-a", "--average", help="Specify how many values "
                        "should we average to smooth the curves", default=0,
                        type=int)
    return parser.parse_args()


def process(path_glob, variant, out, average):
    """Process single variant"""
    safe_variant = variant.replace('-', '')
    out.write(CHART1 % (variant, variant, safe_variant, variant, safe_variant,
                        safe_variant))
    name_expr = ['*' in _ for _ in path_glob.split(os.path.sep)]
    color_idx = 0
    no_labels = 0
    for path in glob.glob(path_glob):
        split_path = path.split(os.path.sep)
        name = '/'.join([split_path[i]
                         for i in range(len(name_expr)) if name_expr[i]])
        with open(path, encoding='utf8') as res_fd:
            results = json.load(res_fd)
        samples = None
        for throughputs in results['throughput']['iops_sec']:
            if throughputs["client_hostname"] == "all":
                samples = throughputs["samples"]
                break
        else:
            print(f"No all client for {path}", file=sys.stderr)
            continue
        shade_add = 128 // len(samples)
        shade = 128
        sys.stdout.write(f"{name}")
        for i, sample in enumerate(samples):
            sys.stdout.write(f"; {sample['value']}")
            sample = [_["value"] for _ in sample["timeseries"]]
            if average:
                sample = [sum(sample[i:i + average]) / average
                          for i in range(len(sample) - average)]
            out.write(f'            {{label: "{name}-{i}", data: {sample}, '
                      f'borderColor: "{COLORS[color_idx].format(shade)}"}},\n')
            shade += shade_add
            no_labels = max(no_labels, len(sample))
        sys.stdout.write("\n")
        color_idx += 1
        color_idx %= 7
    out.write(f"        ],\n        labels: {list(range(no_labels))}\n")
    out.write(CHART2)


def run():
    """Run the extraction"""
    args = parse_args()
    with open(args.output, 'w', encoding='utf8') as out:
        out.write(HTML1)
        # Get variants
        variants = set()
        for path in glob.glob(os.path.join(args.path_glob, "*/result.json")):
            variants.add(path.rsplit(os.path.sep, 2)[1])
        for variant in sorted(variants):
            process(os.path.join(args.path_glob, variant, "result.json"),
                    variant, out, args.average)
        out.write(HTML2)
    return 0


if __name__ == '__main__':
    sys.exit(run())
