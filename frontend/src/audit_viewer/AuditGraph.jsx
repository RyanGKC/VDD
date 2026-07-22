import React, { useEffect, useState } from 'react';
import ReactFlow, { Background, Controls, MiniMap } from 'reactflow';
import 'reactflow/dist/style.css';
import dagre from 'dagre';

const nodeWidth = 180;
const nodeHeight = 60;

const getLayoutedElements = (nodes, edges) => {
  const dagreGraph = new dagre.graphlib.Graph();
  dagreGraph.setDefaultEdgeLabel(() => ({}));
  dagreGraph.setGraph({ rankdir: 'LR' }); // Left to Right

  nodes.forEach((node) => {
    dagreGraph.setNode(node.id, { width: nodeWidth, height: nodeHeight });
  });

  edges.forEach((edge) => {
    dagreGraph.setEdge(edge.source, edge.target);
  });

  dagre.layout(dagreGraph);

  const layoutedNodes = nodes.map((node) => {
    const nodeWithPosition = dagreGraph.node(node.id);
    return {
      ...node,
      position: {
        x: nodeWithPosition.x - nodeWidth / 2,
        y: nodeWithPosition.y - nodeHeight / 2,
      },
    };
  });

  return { nodes: layoutedNodes, edges };
};

const AuditGraph = ({ data, onNodeClick }) => {
  const [nodes, setNodes] = useState([]);
  const [edges, setEdges] = useState([]);

  useEffect(() => {
    if (data && data.nodes && data.edges) {
      const rfNodes = data.nodes.map((n) => ({
        id: n.id,
        data: { label: n.label },
        position: { x: 0, y: 0 },
        style: { 
          background: '#1e1e24', 
          color: '#fff', 
          border: '1px solid #3f3f4e',
          width: nodeWidth,
          borderRadius: '8px',
          padding: '10px',
          fontWeight: 'bold',
          textAlign: 'center'
        }
      }));
      
      const rfEdges = data.edges.map((e) => ({
        id: e.id,
        source: e.source,
        target: e.target,
        animated: true,
        style: { stroke: '#4da6ff' }
      }));

      const layouted = getLayoutedElements(rfNodes, rfEdges);
      setNodes(layouted.nodes);
      setEdges(layouted.edges);
    }
  }, [data]);

  return (
    <ReactFlow
      nodes={nodes}
      edges={edges}
      onNodeClick={(e, node) => onNodeClick(node)}
      fitView
      attributionPosition="bottom-right"
    >
      <Background color="#3f3f4e" gap={16} />
      <Controls />
      <MiniMap nodeStrokeColor="#3f3f4e" nodeColor="#1e1e24" />
    </ReactFlow>
  );
};

export default AuditGraph;
