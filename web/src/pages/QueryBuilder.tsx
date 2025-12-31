import { useState, useEffect } from 'react';
import type { ObjectType, LinkType, QueryRequest, QueryResult } from '../api/client';
import { schemaApi, queryApi } from '../api/client';
import { 
  PlayIcon, 
  DocumentDuplicateIcon, 
  ArrowPathIcon,
  MagnifyingGlassIcon,
  PlusIcon,
  TrashIcon
} from '@heroicons/react/24/outline';

export default function QueryBuilder() {
  const [objectTypes, setObjectTypes] = useState<ObjectType[]>([]);
  const [linkTypes, setLinkTypes] = useState<LinkType[]>([]);
  const [selectedObjectType, setSelectedObjectType] = useState<ObjectType | null>(null);
  const [query, setQuery] = useState<QueryRequest>({
    from: '',
    select: [],
    where: {},
    links: [],
    orderBy: [],
    limit: 20,
    offset: 0
  });
  const [results, setResults] = useState<QueryResult | null>(null);
  const [loading, setLoading] = useState(false);
  const [showJson, setShowJson] = useState(false);
  const [viewMode, setViewMode] = useState<'table' | 'json'>('table');
  const [whereConditions, setWhereConditions] = useState<Array<{field: string; operator: string; value: string}>>([]);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    loadSchema();
  }, []);

  useEffect(() => {
    if (query.from) {
      const ot = objectTypes.find(o => o.name === query.from);
      setSelectedObjectType(ot || null);
    } else {
      setSelectedObjectType(null);
    }
  }, [query.from, objectTypes]);

  useEffect(() => {
    // 更新 query.where 基于 whereConditions
    const where: Record<string, any> = {};
    whereConditions.forEach(cond => {
      if (cond.field && cond.value) {
        where[cond.field] = cond.value;
      }
    });
    setQuery(prev => ({ ...prev, where }));
  }, [whereConditions]);

  const loadSchema = async () => {
    try {
      const [objectTypesData, linkTypesData] = await Promise.all([
        schemaApi.getObjectTypes(),
        schemaApi.getLinkTypes(),
      ]);
      setObjectTypes(objectTypesData);
      setLinkTypes(linkTypesData);
    } catch (error) {
      console.error('Failed to load schema:', error);
    }
  };

  const executeQuery = async () => {
    if (!query.from) {
      setError('请选择对象类型');
      return;
    }
    if (!query.select || query.select.length === 0) {
      setError('请至少选择一个属性');
      return;
    }

    setLoading(true);
    setError(null);
    try {
      const result = await queryApi.execute(query);
      setResults(result);
    } catch (err: any) {
      setError(err.response?.data?.message || err.message || '查询执行失败');
      setResults(null);
    } finally {
      setLoading(false);
    }
  };

  const addWhereCondition = () => {
    setWhereConditions([...whereConditions, { field: '', operator: '=', value: '' }]);
  };

  const removeWhereCondition = (index: number) => {
    setWhereConditions(whereConditions.filter((_, i) => i !== index));
  };

  const updateWhereCondition = (index: number, field: string, operator: string, value: string) => {
    const updated = [...whereConditions];
    updated[index] = { field, operator, value };
    setWhereConditions(updated);
  };

  const addLink = () => {
    const availableLinks = linkTypes.filter(lt => 
      lt.source_type === query.from || lt.target_type === query.from
    );
    if (availableLinks.length === 0) {
      setError('当前对象类型没有可用的关联类型');
      return;
    }
    setQuery(prev => ({
      ...prev,
      links: [...(prev.links || []), {
        name: availableLinks[0].name,
        select: [],
      }]
    }));
  };

  const removeLink = (index: number) => {
    setQuery(prev => ({
      ...prev,
      links: (prev.links || []).filter((_, i) => i !== index)
    }));
  };

  const updateLinkSelect = (linkIndex: number, propertyName: string, checked: boolean) => {
    setQuery(prev => {
      const links = [...(prev.links || [])];
      const link = { ...links[linkIndex] };
      if (checked) {
        link.select = [...(link.select || []), propertyName];
      } else {
        link.select = (link.select || []).filter(s => s !== propertyName);
      }
      links[linkIndex] = link;
      return { ...prev, links };
    });
  };

  const addOrderBy = () => {
    setQuery(prev => ({
      ...prev,
      orderBy: [...(prev.orderBy || []), { field: '', direction: 'ASC' }]
    }));
  };

  const removeOrderBy = (index: number) => {
    setQuery(prev => ({
      ...prev,
      orderBy: (prev.orderBy || []).filter((_, i) => i !== index)
    }));
  };

  const updateOrderBy = (index: number, field: string, direction: 'ASC' | 'DESC') => {
    setQuery(prev => {
      const orderBy = [...(prev.orderBy || [])];
      orderBy[index] = { field, direction };
      return { ...prev, orderBy };
    });
  };

  const copyQueryJson = () => {
    navigator.clipboard.writeText(JSON.stringify(query, null, 2));
  };

  const exportResults = () => {
    if (!results) return;
    const json = JSON.stringify(results, null, 2);
    const blob = new Blob([json], { type: 'application/json' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = `query-results-${Date.now()}.json`;
    a.click();
    URL.revokeObjectURL(url);
  };

  const getAvailableLinks = (objectTypeName: string) => {
    return linkTypes.filter(lt => {
      // 如果是 directed（有向），只有当 objectTypeName 是 source_type 时才能作为关联查询
      if (lt.direction === 'directed') {
        return lt.source_type === objectTypeName;
      }
      // 如果是 undirected（无向），objectTypeName 可以是 source_type 或 target_type
      return lt.source_type === objectTypeName || lt.target_type === objectTypeName;
    });
  };

  const getLinkTargetType = (linkTypeName: string) => {
    const linkType = linkTypes.find(lt => lt.name === linkTypeName);
    if (!linkType || !query.from) return null;
    
    // 如果是 directed（有向），只能从 source 到 target
    if (linkType.direction === 'directed') {
      if (linkType.source_type === query.from) {
        return objectTypes.find(ot => ot.name === linkType.target_type);
      }
      // directed link 不能反向查询
      return null;
    }
    
    // 如果是 undirected（无向），可以从 source 到 target，也可以从 target 到 source
    if (linkType.source_type === query.from) {
      return objectTypes.find(ot => ot.name === linkType.target_type);
    }
    if (linkType.target_type === query.from) {
      return objectTypes.find(ot => ot.name === linkType.source_type);
    }
    
    return null;
  };

  return (
    <div className="flex h-full bg-gray-50">
      {/* 左侧：查询构建器 */}
      <div className="w-1/2 border-r border-gray-200 overflow-y-auto p-6">
        <div className="flex items-center justify-between mb-6">
          <h2 className="text-xl font-bold text-gray-900">查询构建器</h2>
        </div>

        {/* 对象类型选择 */}
        <div className="mb-6">
          <label className="block text-sm font-medium text-gray-700 mb-2">
            对象类型 <span className="text-red-500">*</span>
          </label>
          <select
            value={query.from}
            onChange={(e) => {
              setQuery({ ...query, from: e.target.value, select: [] });
              setWhereConditions([]);
            }}
            className="w-full border border-gray-300 rounded-lg px-3 py-2 focus:outline-none focus:ring-2 focus:ring-blue-500"
          >
            <option value="">选择对象类型...</option>
            {objectTypes.map(ot => (
              <option key={ot.name} value={ot.name}>{ot.name}</option>
            ))}
          </select>
        </div>

        {/* 属性选择 */}
        {selectedObjectType && (
          <div className="mb-6">
            <label className="block text-sm font-medium text-gray-700 mb-2">
              选择属性 <span className="text-red-500">*</span>
            </label>
            <div className="space-y-2 border border-gray-300 rounded-lg p-3 max-h-48 overflow-y-auto bg-white">
              {selectedObjectType.properties.map(prop => (
                <label key={prop.name} className="flex items-center cursor-pointer hover:bg-gray-50 p-1 rounded">
                  <input
                    type="checkbox"
                    checked={query.select?.includes(prop.name) || false}
                    onChange={(e) => {
                      if (e.target.checked) {
                        setQuery({ ...query, select: [...(query.select || []), prop.name] });
                      } else {
                        setQuery({ ...query, select: (query.select || []).filter(s => s !== prop.name) });
                      }
                    }}
                    className="mr-2"
                  />
                  <span className="text-sm text-gray-900">{prop.name}</span>
                  <span className="text-xs text-gray-500 ml-2">({prop.data_type})</span>
                </label>
              ))}
            </div>
          </div>
        )}

        {/* WHERE 条件 */}
        <div className="mb-6">
          <div className="flex items-center justify-between mb-2">
            <label className="block text-sm font-medium text-gray-700">查询条件</label>
            <button
              onClick={addWhereCondition}
              className="text-sm text-blue-600 hover:text-blue-800 flex items-center"
            >
              <PlusIcon className="w-4 h-4 mr-1" />
              添加条件
            </button>
          </div>
          <div className="space-y-2">
            {whereConditions.map((cond, index) => (
              <div key={index} className="flex gap-2 items-center">
                <select
                  value={cond.field}
                  onChange={(e) => updateWhereCondition(index, e.target.value, cond.operator, cond.value)}
                  className="flex-1 border border-gray-300 rounded px-2 py-1 text-sm"
                >
                  <option value="">选择属性...</option>
                  {selectedObjectType?.properties.map(prop => (
                    <option key={prop.name} value={prop.name}>{prop.name}</option>
                  ))}
                </select>
                <select
                  value={cond.operator}
                  onChange={(e) => updateWhereCondition(index, cond.field, e.target.value, cond.value)}
                  className="border border-gray-300 rounded px-2 py-1 text-sm"
                >
                  <option value="=">=</option>
                  <option value=">">&gt;</option>
                  <option value="<">&lt;</option>
                  <option value="LIKE">LIKE</option>
                </select>
                <input
                  type="text"
                  value={cond.value}
                  onChange={(e) => updateWhereCondition(index, cond.field, cond.operator, e.target.value)}
                  placeholder="值"
                  className="flex-1 border border-gray-300 rounded px-2 py-1 text-sm"
                />
                <button
                  onClick={() => removeWhereCondition(index)}
                  className="text-red-600 hover:text-red-800"
                >
                  <TrashIcon className="w-4 h-4" />
                </button>
              </div>
            ))}
          </div>
        </div>

        {/* 关联查询 */}
        <div className="mb-6">
          <div className="flex items-center justify-between mb-2">
            <label className="block text-sm font-medium text-gray-700">关联查询</label>
            <button
              onClick={addLink}
              disabled={!query.from}
              className="text-sm text-blue-600 hover:text-blue-800 flex items-center disabled:text-gray-400"
            >
              <PlusIcon className="w-4 h-4 mr-1" />
              添加关联
            </button>
          </div>
          <div className="space-y-3">
            {query.links?.map((link, linkIndex) => {
              const targetType = getLinkTargetType(link.name);
              return (
                <div key={linkIndex} className="border border-gray-300 rounded-lg p-3 bg-gray-50">
                  <div className="flex items-center justify-between mb-2">
                    <select
                      value={link.name}
                      onChange={(e) => {
                        setQuery(prev => {
                          const links = [...(prev.links || [])];
                          // 当关联类型改变时，清空已选择的属性
                          links[linkIndex] = { ...links[linkIndex], name: e.target.value, select: [] };
                          return { ...prev, links };
                        });
                      }}
                      className="flex-1 border border-gray-300 rounded px-2 py-1 text-sm mr-2"
                    >
                      <option value="">选择关联类型...</option>
                      {getAvailableLinks(query.from).map(lt => (
                        <option key={lt.name} value={lt.name}>{lt.name}</option>
                      ))}
                    </select>
                    <button
                      onClick={() => removeLink(linkIndex)}
                      className="text-red-600 hover:text-red-800"
                    >
                      <TrashIcon className="w-4 h-4" />
                    </button>
                  </div>
                  {targetType && (
                    <div className="mt-2 space-y-1">
                      <label className="text-xs text-gray-600">选择属性:</label>
                      <div className="space-y-1 max-h-32 overflow-y-auto">
                        {targetType.properties.map(prop => (
                          <label key={prop.name} className="flex items-center cursor-pointer hover:bg-white p-1 rounded">
                            <input
                              type="checkbox"
                              checked={link.select?.includes(prop.name) || false}
                              onChange={(e) => updateLinkSelect(linkIndex, prop.name, e.target.checked)}
                              className="mr-2"
                            />
                            <span className="text-xs text-gray-900">{prop.name}</span>
                          </label>
                        ))}
                      </div>
                    </div>
                  )}
                </div>
              );
            })}
          </div>
        </div>

        {/* 排序和分页 */}
        <div className="mb-6">
          <label className="block text-sm font-medium text-gray-700 mb-2">排序</label>
          <div className="space-y-2">
            {query.orderBy?.map((order, index) => (
              <div key={index} className="flex gap-2 items-center">
                <select
                  value={order.field}
                  onChange={(e) => updateOrderBy(index, e.target.value, order.direction)}
                  className="flex-1 border border-gray-300 rounded px-2 py-1 text-sm"
                >
                  <option value="">选择属性...</option>
                  {selectedObjectType?.properties.map(prop => (
                    <option key={prop.name} value={prop.name}>{prop.name}</option>
                  ))}
                </select>
                <select
                  value={order.direction}
                  onChange={(e) => updateOrderBy(index, order.field, e.target.value as 'ASC' | 'DESC')}
                  className="border border-gray-300 rounded px-2 py-1 text-sm"
                >
                  <option value="ASC">ASC</option>
                  <option value="DESC">DESC</option>
                </select>
                <button
                  onClick={() => removeOrderBy(index)}
                  className="text-red-600 hover:text-red-800"
                >
                  <TrashIcon className="w-4 h-4" />
                </button>
              </div>
            ))}
            <button
              onClick={addOrderBy}
              className="text-sm text-blue-600 hover:text-blue-800 flex items-center"
            >
              <PlusIcon className="w-4 h-4 mr-1" />
              添加排序
            </button>
          </div>
        </div>

        <div className="mb-6 grid grid-cols-2 gap-4">
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1">每页数量</label>
            <input
              type="number"
              value={query.limit || 20}
              onChange={(e) => setQuery({ ...query, limit: parseInt(e.target.value) || 20 })}
              className="w-full border border-gray-300 rounded px-2 py-1 text-sm"
              min="1"
            />
          </div>
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1">偏移量</label>
            <input
              type="number"
              value={query.offset || 0}
              onChange={(e) => setQuery({ ...query, offset: parseInt(e.target.value) || 0 })}
              className="w-full border border-gray-300 rounded px-2 py-1 text-sm"
              min="0"
            />
          </div>
        </div>

        {/* JSON 预览 */}
        <div className="mb-6">
          <div className="flex items-center justify-between mb-2">
            <label className="block text-sm font-medium text-gray-700">查询 JSON</label>
            <div className="flex gap-2">
              <button
                onClick={copyQueryJson}
                className="text-sm text-blue-600 hover:text-blue-800 flex items-center"
                title="复制 JSON"
              >
                <DocumentDuplicateIcon className="w-4 h-4 mr-1" />
              </button>
              <button
                onClick={() => setShowJson(!showJson)}
                className="text-sm text-blue-600 hover:text-blue-800"
              >
                {showJson ? '隐藏' : '显示'} JSON
              </button>
            </div>
          </div>
          {showJson && (
            <textarea
              className="w-full font-mono text-xs p-2 border border-gray-300 rounded"
              rows={10}
              value={JSON.stringify(query, null, 2)}
              onChange={(e) => {
                try {
                  const parsed = JSON.parse(e.target.value);
                  setQuery(parsed);
                } catch (err) {
                  // 忽略无效 JSON
                }
              }}
            />
          )}
        </div>

        {/* 错误提示 */}
        {error && (
          <div className="mb-4 p-3 bg-red-50 border border-red-200 rounded text-sm text-red-700">
            {error}
          </div>
        )}

        {/* 执行按钮 */}
        <button
          onClick={executeQuery}
          disabled={loading || !query.from || !query.select || query.select.length === 0}
          className="w-full flex items-center justify-center px-4 py-2 bg-blue-600 text-white rounded-lg hover:bg-blue-700 disabled:bg-gray-400 disabled:cursor-not-allowed transition-colors"
        >
          {loading ? (
            <>
              <ArrowPathIcon className="w-5 h-5 animate-spin mr-2" />
              执行中...
            </>
          ) : (
            <>
              <PlayIcon className="w-5 h-5 mr-2" />
              执行查询
            </>
          )}
        </button>
      </div>

      {/* 右侧：查询结果 */}
      <div className="w-1/2 overflow-y-auto p-6">
        <div className="flex items-center justify-between mb-4">
          <h2 className="text-xl font-bold text-gray-900">查询结果</h2>
          {results && (
            <div className="flex items-center gap-2">
              <button
                onClick={exportResults}
                className="text-sm text-blue-600 hover:text-blue-800 flex items-center"
              >
                <DocumentDuplicateIcon className="w-4 h-4 mr-1" />
                导出
              </button>
              <button
                onClick={() => setViewMode(viewMode === 'table' ? 'json' : 'table')}
                className="text-sm text-blue-600 hover:text-blue-800"
              >
                {viewMode === 'table' ? 'JSON 视图' : '表格视图'}
              </button>
            </div>
          )}
        </div>

        {results ? (
          <div>
            <div className="mb-4 text-sm text-gray-600">
              共 {results.rowCount} 条结果
            </div>
            {viewMode === 'table' ? (
              <div className="overflow-x-auto">
                <table className="min-w-full divide-y divide-gray-200 bg-white rounded-lg shadow">
                  <thead className="bg-gray-50">
                    <tr>
                      {results.columns.map(col => (
                        <th
                          key={col}
                          className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider"
                        >
                          {col}
                        </th>
                      ))}
                    </tr>
                  </thead>
                  <tbody className="bg-white divide-y divide-gray-200">
                    {results.rows.map((row, idx) => (
                      <tr key={idx} className="hover:bg-gray-50">
                        {results.columns.map(col => (
                          <td
                            key={col}
                            className="px-6 py-4 whitespace-nowrap text-sm text-gray-900"
                          >
                            {row[col] !== null && row[col] !== undefined ? String(row[col]) : 'null'}
                          </td>
                        ))}
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            ) : (
              <pre className="p-4 overflow-auto bg-gray-50 text-sm rounded border border-gray-200">
                {JSON.stringify(results, null, 2)}
              </pre>
            )}
          </div>
        ) : (
          <div className="text-center text-gray-500 py-12">
            <MagnifyingGlassIcon className="w-12 h-12 mx-auto mb-4 text-gray-400" />
            <p>点击"执行查询"查看结果</p>
          </div>
        )}
      </div>
    </div>
  );
}

