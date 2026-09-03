import { GraphEdge } from "@/lib/api";

export interface LayoutNode {
  name: string;
  x: number;
  y: number;
}

export interface GraphLayout {
  nodes: LayoutNode[];
  width: number;
  height: number;
}

const LAYER_GAP_X = 190;
const NODE_GAP_Y = 84;
const MARGIN = 70;

/**
 * Lays out an arbitrary real topology by BFS depth from root nodes
 * (services with no incoming edges) -- roughly what a typical service
 * architecture already looks like conceptually (a gateway fanning out
 * to services, services fanning out to datastores), so this tends to
 * produce a readable left-to-right diagram without needing a full
 * force-directed simulation or a new layout-library dependency.
 *
 * Nodes unreachable from any root (a genuine cycle with no clear
 * entry point) fall back to layer 0 rather than being dropped --
 * every discovered service must appear somewhere on the map.
 */
export function layoutGraph(edges: GraphEdge[]): GraphLayout {
  const allNodes = new Set<string>();
  edges.forEach((e) => {
    allNodes.add(e.caller);
    allNodes.add(e.callee);
  });

  const fanIn: Record<string, number> = {};
  const adjacency: Record<string, string[]> = {};
  allNodes.forEach((n) => {
    fanIn[n] = 0;
    adjacency[n] = [];
  });
  edges.forEach((e) => {
    fanIn[e.callee] = (fanIn[e.callee] ?? 0) + 1;
    adjacency[e.caller].push(e.callee);
  });

  const roots = [...allNodes].filter((n) => fanIn[n] === 0);
  const startNodes = roots.length > 0 ? roots : [...allNodes].slice(0, 1);

  const layer: Record<string, number> = {};
  const visited = new Set<string>();
  const queue: [string, number][] = startNodes.map((n) => [n, 0]);
  while (queue.length) {
    const [node, depth] = queue.shift()!;
    if (visited.has(node)) continue;
    visited.add(node);
    layer[node] = depth;
    for (const child of adjacency[node] ?? []) {
      if (!visited.has(child)) queue.push([child, depth + 1]);
    }
  }
  allNodes.forEach((n) => {
    if (!(n in layer)) layer[n] = 0;
  });

  const byLayer: Record<number, string[]> = {};
  allNodes.forEach((n) => {
    const l = layer[n];
    (byLayer[l] ??= []).push(n);
  });

  const nodes: LayoutNode[] = [];
  let maxLayer = 0;
  let maxPerLayer = 0;
  Object.entries(byLayer).forEach(([l, names]) => {
    const layerNum = Number(l);
    maxLayer = Math.max(maxLayer, layerNum);
    maxPerLayer = Math.max(maxPerLayer, names.length);
    names.forEach((name, i) => {
      nodes.push({ name, x: MARGIN + layerNum * LAYER_GAP_X, y: MARGIN + i * NODE_GAP_Y });
    });
  });

  return {
    nodes,
    width: MARGIN * 2 + maxLayer * LAYER_GAP_X + 120,
    height: MARGIN * 2 + Math.max(maxPerLayer - 1, 0) * NODE_GAP_Y + 50,
  };
}