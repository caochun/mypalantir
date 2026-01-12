import { useEffect, useState } from 'react';
import { useParams, Link } from 'react-router-dom';
import type { Instance, ObjectType, QueryRequest } from '../api/client';
import { instanceApi, schemaApi, queryApi } from '../api/client';
import { PlusIcon, PencilIcon, TrashIcon } from '@heroicons/react/24/outline';
import InstanceForm from '../components/InstanceForm';

export default function InstanceList() {
  const { objectType } = useParams<{ objectType: string }>();
  const [instances, setInstances] = useState<Instance[]>([]);
  const [objectTypeDef, setObjectTypeDef] = useState<ObjectType | null>(null);
  const [loading, setLoading] = useState(true);
  const [showForm, setShowForm] = useState(false);
  const [editingInstance, setEditingInstance] = useState<Instance | null>(null);
  const [total, setTotal] = useState(0);
  const [offset, setOffset] = useState(0);
  const limit = 20;

  useEffect(() => {
    if (objectType) {
      loadData();
    }
  }, [objectType, offset]);

  const loadData = async () => {
    if (!objectType) return;
    try {
      setLoading(true);
      
      // 首先获取对象类型定义
      const objectTypeData = await schemaApi.getObjectType(objectType);
      setObjectTypeDef(objectTypeData);
      
      // 构建 ontology query：查询当前 object type 的所有实例
      const selectFields: string[] = ['id']; // 首先添加 id 字段（查询系统会自动映射 id_column 为 id）
      
      // 添加所有属性字段
      if (objectTypeData.properties) {
        objectTypeData.properties.forEach(prop => {
          selectFields.push(prop.name);
        });
      }
      
      const queryRequest: QueryRequest = {
        object: objectType,
        select: selectFields,
        limit: limit,
        offset: offset,
      };
      
      // 执行 ontology query
      const queryResult = await queryApi.execute(queryRequest);
      
      // 将查询结果转换为实例列表格式
      // queryResult.rows 是 Record<string, any>[]，每行是一个对象，键是列名（ontology 属性名）
      // 查询系统会自动将数据库的 id_column 映射为 "id" 字段
      const instances: Instance[] = queryResult.rows.map((row: Record<string, any>) => {
        const instance: Instance = {
          id: row.id || '', // 查询系统已将 id_column 映射为 "id"
          ...row, // 包含所有其他字段（包括 id 和所有属性）
        };
        return instance;
      });
      
      setInstances(instances);
      // 使用 rowCount 作为总数（如果返回了准确的总数）
      // 否则使用当前返回的行数作为估算
      setTotal(queryResult.rowCount || instances.length);
    } catch (error) {
      console.error('Failed to load data:', error);
    } finally {
      setLoading(false);
    }
  };

  const handleCreate = () => {
    setEditingInstance(null);
    setShowForm(true);
  };

  const handleEdit = (instance: Instance) => {
    setEditingInstance(instance);
    setShowForm(true);
  };

  const handleDelete = async (id: string) => {
    if (!objectType) return;
    if (!confirm('Are you sure you want to delete this instance?')) return;
    try {
      await instanceApi.delete(objectType, id);
      loadData();
    } catch (error) {
      console.error('Failed to delete instance:', error);
      alert('Failed to delete instance');
    }
  };

  const handleFormClose = () => {
    setShowForm(false);
    setEditingInstance(null);
    loadData();
  };

  if (loading) {
    return <div className="text-center py-12">Loading...</div>;
  }

  if (!objectTypeDef) {
    return <div className="text-center py-12">Object type not found</div>;
  }

  return (
    <div>
      <div className="flex items-center justify-between mb-6">
        <div>
          <h1 className="text-2xl font-bold text-gray-900">{objectTypeDef.name}</h1>
          {objectTypeDef.description && (
            <p className="text-gray-600 mt-1">{objectTypeDef.description}</p>
          )}
        </div>
        <button
          onClick={handleCreate}
          className="flex items-center px-4 py-2 bg-blue-600 text-white rounded-lg hover:bg-blue-700 transition-colors"
        >
          <PlusIcon className="w-5 h-5 mr-2" />
          Create Instance
        </button>
      </div>

      {showForm && (
        <InstanceForm
          objectType={objectTypeDef}
          instance={editingInstance}
          onClose={handleFormClose}
        />
      )}

      <div className="bg-white rounded-lg shadow-sm border border-gray-200 overflow-hidden">
        <div className="overflow-x-auto">
          <table className="min-w-full divide-y divide-gray-200">
            <thead className="bg-gray-50">
              <tr>
                <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">
                  ID
                </th>
                {objectTypeDef.properties.map((prop) => (
                  <th
                    key={prop.name}
                    className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider"
                  >
                    {prop.name}
                  </th>
                ))}
                <th className="px-6 py-3 text-right text-xs font-medium text-gray-500 uppercase tracking-wider">
                  Actions
                </th>
              </tr>
            </thead>
            <tbody className="bg-white divide-y divide-gray-200">
              {instances.length === 0 ? (
                <tr>
                  <td
                    colSpan={objectTypeDef.properties.length + 2}
                    className="px-6 py-8 text-center text-gray-500"
                  >
                    No instances found. Create one to get started.
                  </td>
                </tr>
              ) : (
                instances.map((instance) => (
                  <tr key={instance.id} className="hover:bg-gray-50">
                    <td className="px-6 py-4 whitespace-nowrap">
                      <Link
                        to={`/instances/${objectType}/${instance.id}`}
                        className="text-blue-600 hover:text-blue-800 text-sm font-mono"
                      >
                        {instance.id.substring(0, 8)}...
                      </Link>
                    </td>
                    {objectTypeDef.properties.map((prop) => (
                      <td key={prop.name} className="px-6 py-4 whitespace-nowrap text-sm text-gray-900">
                        {instance[prop.name] !== null && instance[prop.name] !== undefined
                          ? typeof instance[prop.name] === 'object'
                            ? JSON.stringify(instance[prop.name])
                            : String(instance[prop.name])
                          : '-'}
                      </td>
                    ))}
                    <td className="px-6 py-4 whitespace-nowrap text-right text-sm font-medium">
                      <div className="flex items-center justify-end gap-2">
                        <button
                          onClick={() => handleEdit(instance)}
                          className="text-blue-600 hover:text-blue-800"
                          title="Edit"
                        >
                          <PencilIcon className="w-4 h-4" />
                        </button>
                        <button
                          onClick={() => handleDelete(instance.id)}
                          className="text-red-600 hover:text-red-800"
                          title="Delete"
                        >
                          <TrashIcon className="w-4 h-4" />
                        </button>
                      </div>
                    </td>
                  </tr>
                ))
              )}
            </tbody>
          </table>
        </div>

        {total > limit && (
          <div className="bg-gray-50 px-6 py-3 flex items-center justify-between border-t border-gray-200">
            <div className="text-sm text-gray-700">
              Showing {offset + 1} to {Math.min(offset + limit, total)} of {total} instances
            </div>
            <div className="flex gap-2">
              <button
                onClick={() => setOffset(Math.max(0, offset - limit))}
                disabled={offset === 0}
                className="px-3 py-1 text-sm border border-gray-300 rounded hover:bg-gray-100 disabled:opacity-50 disabled:cursor-not-allowed"
              >
                Previous
              </button>
              <button
                onClick={() => setOffset(offset + limit)}
                disabled={offset + limit >= total}
                className="px-3 py-1 text-sm border border-gray-300 rounded hover:bg-gray-100 disabled:opacity-50 disabled:cursor-not-allowed"
              >
                Next
              </button>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}

