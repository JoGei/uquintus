#!/usr/bin/env python3
"""Export the pinned CorePerfDSL scheduling graph, without parsing generated C++."""
import argparse
from collections import deque
import json
from pathlib import Path
import sys


def export(generator, description):
    sys.path.insert(0, str(Path(generator)/'m2isar_perf'))
    from frontends.corePerfDsl import api
    from meta_models.scheduling_model.SchedulingTransformer import SchedulingTransformer
    from meta_models.scheduling_model.SchedulingModel import Node, StaticEdge, DynamicEdge
    model = SchedulingTransformer().transform(api.execute(str(description), None))
    variant, = model.getAllVariants()

    def edge(e):
        if isinstance(e, Node):
            return ['node', e.name]
        if isinstance(e, StaticEdge):
            if e.getTimingVariable().hasMultiElements():
                raise ValueError('block adapter requires scalar timing variables')
            return ['state', e.getTimingVariable().name]
        if isinstance(e, DynamicEdge):
            return ['connector', e.getConnectorModel().name, e.name]
        raise ValueError('unknown scheduling graph edge')

    instructions = {}
    for f in variant.getAllSchedulingFunctions():
        pending, visited, nodes = deque([f.getRootNode()]), set(), []
        while pending:
            node = pending.popleft()
            if node in visited:
                continue
            visited.add(node)
            dynamic = node.getResourceModel().name if node.hasDynamicDelay() else None
            nodes.append(dict(name=node.name, delay=node.getDelay() if dynamic is None else None,
                              dynamic_resource=dynamic,
                              inputs=[edge(e) for e in node.getAllInElements()],
                              outputs=[edge(e) for e in node.getAllOutEdges()]))
            pending.extend(node.getAllOutNodes())
        instructions[str(f.identifier)] = dict(name=f.name, branch=f.isBranch, nodes=nodes)
    return dict(schema_version=1, name=variant.name,
                states=[v.name for v in variant.getAllTimingVariables()], instructions=instructions)


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('generator', type=Path)
    p.add_argument('description', type=Path)
    p.add_argument('output', type=Path)
    a = p.parse_args()
    a.output.write_text(json.dumps(export(a.generator, a.description), indent=2)+'\n')
