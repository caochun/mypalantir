import { useEffect, useState, useCallback } from 'react';
import ForceGraph2D from 'react-force-graph-2d';
import type { ObjectType, LinkType } from '../api/client';
import { schemaApi } from '../api/client';
import { 
  ArrowPathIcon,
  CubeIcon
} from '@heroicons/react/24/outline';

interface SchemaNode {
  id: string;
  name: string;
  description: string;
  type: 'object_type';
  data: ObjectType;
  group?: number;
}

interface SchemaLink {
  source: string;
  target: string;
  id: string;
  name: string;
  description: string;
  cardinality: string;
  direction: string;
  data: LinkType;
}

// 节点颜色映射
const nodeColors = [
  '#3b82f6', // blue
  '#10b981', // green
  '#f59e0b', // orange
  '#ef4444', // red
  '#8b5cf6', // purple
  '#ec4899', // pink
  '#06b6d4', // cyan
  '#84cc16', // lime
];

// 根据对象类型名称生成颜色
const getNodeColor = (name: string): string => {
  let hash = 0;
  for (let i = 0; i < name.length; i++) {
    hash = name.charCodeAt(i) + ((hash << 5) - hash);
  }
  return nodeColors[Math.abs(hash) % nodeColors.length];
};

export default function SchemaGraphView() {
  const [nodes, setNodes] = useState<SchemaNode[]>([]);
  const [links, setLinks] = useState<SchemaLink[]>([]);
  const [loading, setLoading] = useState(true);
  const [selectedNode, setSelectedNode] = useState<SchemaNode | null>(null);
  const [selectedLink, setSelectedLink] = useState<SchemaLink | null>(null);
  const [graphData, setGraphData] = useState({ nodes, links });

  useEffect(() => {
    loadSchemaGraph();
  }, []);

  const loadSchemaGraph = async () => {
    try {
      setLoading(true);
      
      // 加载所有对象类型和关系类型
      const [objectTypes, linkTypes] = await Promise.all([
        schemaApi.getObjectTypes(),
        schemaApi.getLinkTypes(),
      ]);

      // 创建节点（对象类型）
      const schemaNodes: SchemaNode[] = objectTypes.map((ot, index) => ({
        id: ot.name,
        name: ot.name,
        description: ot.description || '',
        type: 'object_type',
        data: ot,
        group: index % nodeColors.length,
      }));

      // 创建边（关系类型）
      const schemaLinks: SchemaLink[] = linkTypes.map((lt) => {
        // 确保源和目标节点存在
        const sourceExists = schemaNodes.some(n => n.id === lt.source_type);
        const targetExists = schemaNodes.some(n => n.id === lt.target_type);
        
        if (!sourceExists || !targetExists) {
          console.warn(`Link ${lt.name} references non-existent node: ${lt.source_type} -> ${lt.target_type}`);
        }

        return {
          source: lt.source_type,
          target: lt.target_type,
          id: `${lt.name}_${lt.source_type}_${lt.target_type}`,
          name: lt.name,
          description: lt.description || '',
          cardinality: lt.cardinality,
          direction: lt.direction,
          data: lt,
        };
      }).filter(link => {
        // 过滤掉引用不存在节点的边
        return schemaNodes.some(n => n.id === link.source) && 
               schemaNodes.some(n => n.id === link.target);
      });

      setNodes(schemaNodes);
      setLinks(schemaLinks);
      setGraphData({ nodes: schemaNodes, links: schemaLinks });
    } catch (error) {
      console.error('Failed to load schema graph:', error);
    } finally {
      setLoading(false);
    }
  };

  const handleNodeClick = useCallback((node: SchemaNode) => {
    setSelectedNode(node);
    setSelectedLink(null);
  }, []);

  const handleLinkClick = useCallback((link: SchemaLink) => {
    setSelectedLink(link);
    setSelectedNode(null);
  }, []);

  const handleBackgroundClick = useCallback(() => {
    setSelectedNode(null);
    setSelectedLink(null);
  }, []);

  if (loading) {
    return (
      <div className="flex items-center justify-center h-full">
        <div className="text-center">
          <ArrowPathIcon className="h-8 w-8 animate-spin mx-auto text-gray-400 mb-2" />
          <p className="text-gray-500">加载Schema图...</p>
        </div>
      </div>
    );
  }

  return (
    <div className="h-full flex flex-col">
      {/* 标题栏 */}
      <div className="bg-white border-b border-gray-200 px-6 py-4 flex items-center justify-between">
        <div className="flex items-center gap-3">
          <CubeIcon className="h-6 w-6 text-blue-600" />
          <div>
            <h1 className="text-xl font-semibold text-gray-900">Ontology Schema 图</h1>
            <p className="text-sm text-gray-500">展示对象类型和关系类型的定义</p>
          </div>
        </div>
        <div className="flex items-center gap-4">
          <button
            onClick={loadSchemaGraph}
            className="px-4 py-2 text-sm font-medium text-gray-700 bg-white border border-gray-300 rounded-md hover:bg-gray-50 focus:outline-none focus:ring-2 focus:ring-blue-500"
          >
            <ArrowPathIcon className="h-4 w-4 inline mr-2" />
            刷新
          </button>
          <div className="text-sm text-gray-600">
            <span className="font-medium">{nodes.length}</span> 个对象类型 · 
            <span className="font-medium"> {links.length}</span> 个关系类型
          </div>
        </div>
      </div>

      {/* 图视图 */}
      <div className="flex-1 relative bg-white">
        <ForceGraph2D
          graphData={graphData}
          nodeLabel={(node: any) => {
            const n = node as SchemaNode;
            return `${n.name}\n${n.description || ''}`;
          }}
          nodeColor={(node: any) => {
            const n = node as SchemaNode;
            return getNodeColor(n.name);
          }}
          nodeVal={(node: any) => {
            // 根据连接数调整节点大小
            const linkCount = links.filter(l => l.source === node.id || l.target === node.id).length;
            return 8 + Math.min(linkCount * 2, 20);
          }}
          linkLabel={(link: any) => {
            const l = link as SchemaLink;
            return `${l.name}\n${l.description || ''}\n${l.cardinality} (${l.direction})`;
          }}
          linkDirectionalArrowLength={6}
          linkDirectionalArrowRelPos={1}
          linkColor={() => '#94a3b8'}
          linkWidth={2}
          onNodeClick={handleNodeClick}
          onLinkClick={handleLinkClick}
          onBackgroundClick={handleBackgroundClick}
          nodeCanvasObject={(node: any, ctx: CanvasRenderingContext2D, globalScale: number) => {
            const n = node as SchemaNode;
            const label = n.name;
            const fontSize = 12 / globalScale;
            ctx.font = `bold ${fontSize}px Sans-Serif`;
            ctx.textAlign = 'center';
            ctx.textBaseline = 'middle';

            // 绘制节点圆圈
            const r = node.__size || 10;
            ctx.beginPath();
            ctx.arc(node.x || 0, node.y || 0, r, 0, 2 * Math.PI, false);
            ctx.fillStyle = getNodeColor(n.name);
            ctx.fill();
            ctx.strokeStyle = '#ffffff';
            ctx.lineWidth = 2 / globalScale;
            ctx.stroke();

            // 绘制标签（仅在缩放足够大时）
            if (globalScale > 0.5) {
              ctx.fillStyle = '#ffffff';
              ctx.strokeStyle = '#1f2937';
              ctx.lineWidth = 2 / globalScale;
              ctx.strokeText(label, node.x || 0, node.y || 0);
              ctx.fillText(label, node.x || 0, node.y || 0);
            }
          }}
          linkCanvasObject={(link: any, ctx: CanvasRenderingContext2D, globalScale: number) => {
            const l = link as SchemaLink;
            // 绘制关系标签（仅在缩放足够大时）
            if (globalScale > 0.8) {
              const midX = ((link.source.x || 0) + (link.target.x || 0)) / 2;
              const midY = ((link.source.y || 0) + (link.target.y || 0)) / 2;
              
              ctx.font = `${10 / globalScale}px Sans-Serif`;
              ctx.textAlign = 'center';
              ctx.textBaseline = 'middle';
              ctx.fillStyle = '#64748b';
              ctx.strokeStyle = '#ffffff';
              ctx.lineWidth = 3 / globalScale;
              ctx.strokeText(l.name, midX, midY);
              ctx.fillText(l.name, midX, midY);
            }
          }}
          cooldownTicks={100}
          onEngineStop={() => {
            // 图布局完成后可以执行的操作
          }}
        />
      </div>

      {/* 详情面板 - 侧边抽屉 */}
      {(selectedNode || selectedLink) && (
        <div className="absolute top-0 right-0 h-full w-96 bg-white shadow-2xl border-l border-gray-200 z-10 flex flex-col">
          {/* 头部 */}
          <div className="flex items-center justify-between p-6 border-b border-gray-200 bg-gradient-to-r from-blue-50 to-indigo-50">
            <div className="flex-1">
              {selectedNode && (
                <>
                  <h3 className="text-xl font-bold text-gray-900 mb-2">{selectedNode.name}</h3>
                  <span className="inline-block px-3 py-1 text-sm font-semibold rounded-md bg-blue-600 text-white">
                    对象类型
                  </span>
                </>
              )}
              {selectedLink && (
                <>
                  <h3 className="text-xl font-bold text-gray-900 mb-2">{selectedLink.name}</h3>
                  <span className="inline-block px-3 py-1 text-sm font-semibold rounded-md bg-green-600 text-white">
                    关系类型
                  </span>
                </>
              )}
            </div>
            <button
              onClick={() => {
                setSelectedNode(null);
                setSelectedLink(null);
              }}
              className="ml-4 text-gray-400 hover:text-gray-600 hover:bg-gray-100 rounded-full p-2 transition-colors"
              aria-label="关闭"
            >
              <svg className="w-6 h-6" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
              </svg>
            </button>
          </div>

          {/* 内容区域 - 可滚动 */}
          <div className="flex-1 overflow-y-auto p-6">
            {selectedNode && (
              <div className="space-y-6">
                {/* 描述 */}
                {selectedNode.description && (
                  <div className="bg-blue-50 border border-blue-200 rounded-lg p-4">
                    <div className="text-xs font-semibold text-blue-700 uppercase tracking-wide mb-2">描述</div>
                    <p className="text-sm text-gray-800 leading-relaxed">{selectedNode.description}</p>
                  </div>
                )}

                {/* 属性列表 */}
                <div>
                  <h4 className="text-sm font-semibold text-gray-700 mb-4 uppercase tracking-wide">
                    属性定义 ({selectedNode.data.properties.length})
                  </h4>
                  <div className="space-y-3">
                    {selectedNode.data.properties.map((prop, idx) => (
                      <div key={idx} className="bg-white border border-gray-200 rounded-lg p-4 hover:border-blue-300 transition-colors">
                        <div className="flex items-start justify-between mb-2">
                          <div className="font-semibold text-base text-gray-900">{prop.name}</div>
                          {prop.required && (
                            <span className="px-2 py-0.5 text-xs font-semibold rounded bg-red-100 text-red-700">
                              必填
                            </span>
                          )}
                        </div>
                        <div className="text-sm text-gray-600 mb-2">
                          <span className="font-medium">类型:</span> {prop.data_type}
                        </div>
                        {prop.description && (
                          <div className="text-sm text-gray-500 mt-2 pt-2 border-t border-gray-100">
                            {prop.description}
                          </div>
                        )}
                        {prop.constraints && Object.keys(prop.constraints).length > 0 && (
                          <div className="mt-2 pt-2 border-t border-gray-100">
                            <div className="text-xs font-semibold text-gray-500 mb-1">约束条件:</div>
                            <div className="text-xs text-gray-600">
                              {Object.entries(prop.constraints).map(([key, value]) => (
                                <div key={key} className="inline-block mr-2 mb-1 px-2 py-0.5 bg-gray-100 rounded">
                                  {key}: {String(value)}
                                </div>
                              ))}
                            </div>
                          </div>
                        )}
                      </div>
                    ))}
                  </div>
                </div>
              </div>
            )}

            {selectedLink && (
              <div className="space-y-6">
                {/* 描述 */}
                {selectedLink.description && (
                  <div className="bg-green-50 border border-green-200 rounded-lg p-4">
                    <div className="text-xs font-semibold text-green-700 uppercase tracking-wide mb-2">描述</div>
                    <p className="text-sm text-gray-800 leading-relaxed">{selectedLink.description}</p>
                  </div>
                )}

                {/* 关系信息 */}
                <div className="bg-gray-50 border border-gray-200 rounded-lg p-4">
                  <h4 className="text-sm font-semibold text-gray-700 mb-3 uppercase tracking-wide">关系信息</h4>
                  {selectedLink.direction === 'undirected' ? (
                    <div className="space-y-3">
                      <div>
                        <div className="text-xs font-semibold text-gray-500 mb-1">对象类型</div>
                        <div className="text-base font-medium text-gray-900">
                          {selectedLink.data.source_type} ↔ {selectedLink.data.target_type}
                          <span className="text-xs text-gray-500 ml-2">(双向关系)</span>
                        </div>
                      </div>
                      <div className="grid grid-cols-2 gap-4">
                        <div>
                          <div className="text-xs font-semibold text-gray-500 mb-1">基数</div>
                          <div className="text-base font-medium text-gray-900">{selectedLink.cardinality}</div>
                        </div>
                        <div>
                          <div className="text-xs font-semibold text-gray-500 mb-1">方向</div>
                          <div className="text-base font-medium text-gray-900">无向 (Undirected)</div>
                        </div>
                      </div>
                    </div>
                  ) : (
                    <div className="grid grid-cols-2 gap-4">
                      <div>
                        <div className="text-xs font-semibold text-gray-500 mb-1">源类型</div>
                        <div className="text-base font-medium text-gray-900">{selectedLink.data.source_type}</div>
                      </div>
                      <div>
                        <div className="text-xs font-semibold text-gray-500 mb-1">目标类型</div>
                        <div className="text-base font-medium text-gray-900">{selectedLink.data.target_type}</div>
                      </div>
                      <div>
                        <div className="text-xs font-semibold text-gray-500 mb-1">基数</div>
                        <div className="text-base font-medium text-gray-900">{selectedLink.cardinality}</div>
                      </div>
                      <div>
                        <div className="text-xs font-semibold text-gray-500 mb-1">方向</div>
                        <div className="text-base font-medium text-gray-900">有向 (Directed)</div>
                      </div>
                    </div>
                  )}
                </div>

                {/* 关系属性 */}
                {selectedLink.data.properties && selectedLink.data.properties.length > 0 && (
                  <div>
                    <h4 className="text-sm font-semibold text-gray-700 mb-4 uppercase tracking-wide">
                      关系属性 ({selectedLink.data.properties.length})
                    </h4>
                    <div className="space-y-3">
                      {selectedLink.data.properties.map((prop, idx) => (
                        <div key={idx} className="bg-white border border-gray-200 rounded-lg p-4 hover:border-green-300 transition-colors">
                          <div className="flex items-start justify-between mb-2">
                            <div className="font-semibold text-base text-gray-900">{prop.name}</div>
                            {prop.required && (
                              <span className="px-2 py-0.5 text-xs font-semibold rounded bg-red-100 text-red-700">
                                必填
                              </span>
                            )}
                          </div>
                          <div className="text-sm text-gray-600">
                            <span className="font-medium">类型:</span> {prop.data_type}
                          </div>
                          {prop.description && (
                            <div className="text-sm text-gray-500 mt-2 pt-2 border-t border-gray-100">
                              {prop.description}
                            </div>
                          )}
                        </div>
                      ))}
                    </div>
                  </div>
                )}
              </div>
            )}
          </div>
        </div>
      )}

      {/* 图例 */}
      <div className="absolute top-20 right-4 bg-white border border-gray-200 rounded-lg shadow-lg p-4 text-xs">
        <div className="font-semibold text-gray-700 mb-2">图例</div>
        <div className="space-y-1">
          <div className="flex items-center gap-2">
            <div className="w-4 h-4 rounded-full bg-blue-500"></div>
            <span>对象类型</span>
          </div>
          <div className="flex items-center gap-2">
            <div className="w-8 h-0.5 bg-slate-400"></div>
            <span>关系类型</span>
          </div>
          <div className="text-gray-500 mt-2">
            点击节点查看详情
          </div>
          <div className="text-gray-500">
            点击边查看关系详情
          </div>
        </div>
      </div>
    </div>
  );
}

