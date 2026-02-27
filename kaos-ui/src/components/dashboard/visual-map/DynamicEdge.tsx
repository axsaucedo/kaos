import React from 'react';
import { getSmoothStepPath, useInternalNode, EdgeLabelRenderer, Position, type EdgeProps } from '@xyflow/react';

// Fallback dimensions if measured not available
const CARD_W = 240;
const CARD_H = 120;

type Side = 'top' | 'bottom' | 'left' | 'right';

function getAnchors(x: number, y: number, w: number, h: number) {
  return {
    top:    { x: x + w / 2, y },
    bottom: { x: x + w / 2, y: y + h },
    left:   { x, y: y + h / 2 },
    right:  { x: x + w, y: y + h / 2 },
  };
}

function dist(a: { x: number; y: number }, b: { x: number; y: number }) {
  return Math.hypot(a.x - b.x, a.y - b.y);
}

const SIDE_TO_POSITION: Record<Side, Position> = {
  top: Position.Top,
  bottom: Position.Bottom,
  left: Position.Left,
  right: Position.Right,
};

function bestAnchors(
  srcPos: { x: number; y: number },
  tgtPos: { x: number; y: number },
  srcW: number, srcH: number,
  tgtW: number, tgtH: number,
) {
  const srcAnchors = getAnchors(srcPos.x, srcPos.y, srcW, srcH);
  const tgtAnchors = getAnchors(tgtPos.x, tgtPos.y, tgtW, tgtH);
  const sides: Side[] = ['top', 'bottom', 'left', 'right'];

  let best = { src: srcAnchors.right, tgt: tgtAnchors.left, srcSide: 'right' as Side, tgtSide: 'left' as Side, d: Infinity };

  for (const ss of sides) {
    for (const ts of sides) {
      const d = dist(srcAnchors[ss], tgtAnchors[ts]);
      if (d < best.d) {
        best = { src: srcAnchors[ss], tgt: tgtAnchors[ts], srcSide: ss, tgtSide: ts, d };
      }
    }
  }
  return best;
}

export function DynamicEdge({
  id, source, target, label, style, markerEnd, animated,
  labelStyle, labelBgStyle,
}: EdgeProps) {
  const sourceNode = useInternalNode(source);
  const targetNode = useInternalNode(target);

  if (!sourceNode || !targetNode) return null;

  const srcPos = sourceNode.internals.positionAbsolute;
  const tgtPos = targetNode.internals.positionAbsolute;

  // Use measured dimensions for precise edge anchoring (fixes gap/drift)
  const srcW = sourceNode.measured?.width ?? CARD_W;
  const srcH = sourceNode.measured?.height ?? CARD_H;
  const tgtW = targetNode.measured?.width ?? CARD_W;
  const tgtH = targetNode.measured?.height ?? CARD_H;

  const { src, tgt, srcSide, tgtSide } = bestAnchors(srcPos, tgtPos, srcW, srcH, tgtW, tgtH);

  const [edgePath, labelX, labelY] = getSmoothStepPath({
    sourceX: src.x,
    sourceY: src.y,
    targetX: tgt.x,
    targetY: tgt.y,
    sourcePosition: SIDE_TO_POSITION[srcSide],
    targetPosition: SIDE_TO_POSITION[tgtSide],
    borderRadius: 8,
  });

  const markerEndStr = typeof markerEnd === 'string'
    ? markerEnd
    : markerEnd && typeof markerEnd === 'object' && 'type' in markerEnd
      ? `url(#${(markerEnd as any).type})`
      : undefined;

  return (
    <>
      <path
        id={id}
        d={edgePath}
        style={style}
        className={`react-flow__edge-path ${animated ? 'react-flow__edge-path--animated' : ''}`}
        markerEnd={markerEndStr}
        fill="none"
      />
      {label && (
        <EdgeLabelRenderer>
          <div
            style={{
              position: 'absolute',
              transform: `translate(-50%, -50%) translate(${labelX}px, ${labelY}px)`,
              pointerEvents: 'none',
              ...(labelBgStyle as any),
              padding: '1px 4px',
              borderRadius: 3,
            }}
          >
            <span style={labelStyle as any}>{label}</span>
          </div>
        </EdgeLabelRenderer>
      )}
    </>
  );
}
