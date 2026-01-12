import { useEffect, useState } from 'react';
import { useParams, Link as RouterLink, useNavigate } from 'react-router-dom';
import type { Instance, ObjectType, QueryRequest } from '../api/client';
import { schemaApi, queryApi } from '../api/client';
import { ArrowLeftIcon, PencilIcon, TrashIcon } from '@heroicons/react/24/outline';
import InstanceForm from '../components/InstanceForm';

export default function InstanceDetail() {
  const { objectType, id } = useParams<{ objectType: string; id: string }>();
  const navigate = useNavigate();
  const [instance, setInstance] = useState<Instance | null>(null);
  const [objectTypeDef, setObjectTypeDef] = useState<ObjectType | null>(null);
  const [loading, setLoading] = useState(true);
  const [showForm, setShowForm] = useState(false);

  useEffect(() => {
    if (objectType && id) {
      loadData();
    }
  }, [objectType, id]);

  const loadData = async () => {
    if (!objectType || !id) return;
    try {
      setLoading(true);
      
      // 获取对象类型定义
      const objectTypeData = await schemaApi.getObjectType(objectType);
      setObjectTypeDef(objectTypeData);

      // 使用 ontology query 查询单个实例
      // 获取 ID 字段名（从 data_source.id_column 或使用第一个属性）
      const idField = objectTypeData.data_source?.id_column || 
                     (objectTypeData.properties && objectTypeData.properties.length > 0 
                       ? objectTypeData.properties[0].name 
                       : 'id');
      
      const selectFields: string[] = ['id']; // 查询结果中会有 id 字段
      if (objectTypeData.properties) {
        objectTypeData.properties.forEach(prop => {
          selectFields.push(prop.name);
        });
      }

      const instanceQuery: QueryRequest = {
        object: objectType,
        select: selectFields,
        filter: [['=', idField, id]], // 使用实际的 ID 字段名
        limit: 1,
      };

      const instanceResult = await queryApi.execute(instanceQuery);
      
      if (instanceResult.rows.length === 0) {
        setLoading(false);
        return;
      }

      const instanceData: Instance = {
        id: instanceResult.rows[0].id || id,
        ...instanceResult.rows[0],
      };
      setInstance(instanceData);

    } catch (error) {
      console.error('Failed to load data:', error);
    } finally {
      setLoading(false);
    }
  };

  const handleDelete = async () => {
    if (!objectType || !id) return;
    if (!confirm('Are you sure you want to delete this instance?')) return;
    try {
      // TODO: 实现删除逻辑
      navigate(`/instances/${objectType}`);
    } catch (error) {
      console.error('Failed to delete instance:', error);
      alert('Failed to delete instance');
    }
  };

  if (loading) {
    return <div className="text-center py-12">Loading...</div>;
  }

  if (!instance || !objectTypeDef) {
    return <div className="text-center py-12">Instance not found</div>;
  }

  return (
    <div className="max-w-4xl mx-auto px-6 py-8">
      {/* 头部 */}
      <div className="mb-6">
        <RouterLink
          to={`/instances/${objectType}`}
          className="inline-flex items-center text-blue-600 hover:text-blue-800 mb-4"
        >
          <ArrowLeftIcon className="w-4 h-4 mr-2" />
          Back to {objectTypeDef.name} List
        </RouterLink>
        <div className="flex items-center justify-between">
          <div>
            <h1 className="text-2xl font-bold text-gray-900">{objectTypeDef.name}</h1>
            <p className="text-sm text-gray-500 font-mono mt-1">ID: {instance.id}</p>
          </div>
          <div className="flex gap-2">
            <button
              onClick={() => setShowForm(true)}
              className="flex items-center px-4 py-2 bg-blue-600 text-white rounded-lg hover:bg-blue-700"
            >
              <PencilIcon className="w-4 h-4 mr-2" />
              Edit
            </button>
            <button
              onClick={handleDelete}
              className="flex items-center px-4 py-2 bg-red-600 text-white rounded-lg hover:bg-red-700"
            >
              <TrashIcon className="w-4 h-4 mr-2" />
              Delete
            </button>
          </div>
        </div>
      </div>

      {showForm && objectTypeDef && (
        <InstanceForm
          objectType={objectTypeDef}
          instance={instance}
          onClose={() => {
            setShowForm(false);
            loadData();
          }}
        />
      )}

      {/* 属性面板 */}
      <div className="bg-white rounded-lg shadow-sm border border-gray-200 p-6">
        <h2 className="text-lg font-semibold text-gray-900 mb-4">Properties</h2>
        <dl className="space-y-4">
          {objectTypeDef.properties.map((prop) => (
            <div key={prop.name}>
              <dt className="text-sm font-medium text-gray-500">{prop.name}</dt>
              <dd className="mt-1 text-sm text-gray-900">
                {instance[prop.name] !== null && instance[prop.name] !== undefined
                  ? typeof instance[prop.name] === 'object'
                    ? (
                        <pre className="bg-gray-50 p-2 rounded text-xs overflow-x-auto">
                          {JSON.stringify(instance[prop.name], null, 2)}
                        </pre>
                      )
                    : String(instance[prop.name])
                  : '-'}
              </dd>
            </div>
          ))}
        </dl>
      </div>
    </div>
  );
}
