import { useEffect, useState } from 'react';
import type { DataSourceConfig } from '../api/client';
import { schemaApi } from '../api/client';
import { 
  ServerIcon,
  InformationCircleIcon,
  CheckCircleIcon,
  XCircleIcon,
  ArrowPathIcon
} from '@heroicons/react/24/outline';

export default function DataSourceManagement() {
  const [dataSources, setDataSources] = useState<DataSourceConfig[]>([]);
  // const [objectTypes, setObjectTypes] = useState<ObjectType[]>([]); // TODO: 用于显示使用该数据源的 ObjectType
  const [loading, setLoading] = useState(true);
  const [selectedDataSource, setSelectedDataSource] = useState<DataSourceConfig | null>(null);
  const [testing, setTesting] = useState(false);
  const [testResult, setTestResult] = useState<{ success: boolean; message: string; metadata?: Record<string, string> } | null>(null);

  useEffect(() => {
    loadData();
  }, []);

  const loadData = async () => {
    try {
      setLoading(true);
      const dataSourcesData = await schemaApi.getDataSources();
      // const objectTypesData = await schemaApi.getObjectTypes(); // TODO: 用于显示使用该数据源的 ObjectType
      setDataSources(dataSourcesData);
      // setObjectTypes(objectTypesData);
      if (dataSourcesData.length > 0) {
        setSelectedDataSource(dataSourcesData[0]);
      }
    } catch (error) {
      console.error('Failed to load data sources:', error);
    } finally {
      setLoading(false);
    }
  };

  // TODO: 查找使用该数据源的 ObjectType
  // 需要扩展 ObjectType 接口以包含 data_source 字段

  const handleTestConnection = async () => {
    if (!selectedDataSource) return;
    
    try {
      setTesting(true);
      setTestResult(null);
      const result = await schemaApi.testConnection(selectedDataSource.id);
      setTestResult(result);
    } catch (error: any) {
      setTestResult({
        success: false,
        message: error.response?.data?.message || error.message || 'Test connection failed'
      });
    } finally {
      setTesting(false);
    }
  };

  // 当选择的数据源改变时，清除测试结果
  useEffect(() => {
    setTestResult(null);
  }, [selectedDataSource?.id]);

  if (loading) {
    return <div className="text-center py-12">Loading...</div>;
  }

  return (
    <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
      {/* 数据源列表 */}
      <div className="bg-white rounded-lg shadow-sm border border-gray-200 p-4">
        <h2 className="text-lg font-semibold text-gray-900 mb-4 flex items-center">
          <ServerIcon className="w-5 h-5 mr-2" />
          Data Sources ({dataSources.length})
        </h2>
        <div className="space-y-2">
          {dataSources.length === 0 ? (
            <div className="text-center py-8 text-gray-500">
              <InformationCircleIcon className="w-12 h-12 mx-auto mb-2 text-gray-400" />
              <p>No data sources configured</p>
              <p className="text-sm mt-2">Configure data sources in schema.yaml</p>
            </div>
          ) : (
            dataSources.map((ds) => (
              <button
                key={ds.id}
                onClick={() => setSelectedDataSource(ds)}
                className={`w-full text-left px-3 py-2 rounded-lg transition-colors ${
                  selectedDataSource?.id === ds.id
                    ? 'bg-blue-50 text-blue-700 border border-blue-200'
                    : 'hover:bg-gray-50 text-gray-700 border border-transparent'
                }`}
              >
                <div className="flex items-center justify-between">
                  <div className="font-medium">{ds.id}</div>
                  <div className="flex items-center">
                    <ServerIcon className="w-4 h-4 mr-1" />
                    <span className="text-xs">{ds.type}</span>
                  </div>
                </div>
                <div className="text-sm text-gray-500 mt-1">
                  {ds.type === 'h2' && ds.host === 'file' 
                    ? `file:${ds.database}` 
                    : ds.type === 'h2' && ds.host === 'mem'
                    ? `mem:${ds.database}`
                    : `${ds.host}:${ds.port}/${ds.database}`}
                </div>
              </button>
            ))
          )}
        </div>
      </div>

      {/* 数据源详情 */}
      <div className="lg:col-span-2 bg-white rounded-lg shadow-sm border border-gray-200 p-6">
        <h2 className="text-lg font-semibold text-gray-900 mb-4">Data Source Details</h2>
        {selectedDataSource ? (
          <div className="space-y-4">
            <div>
              <div className="flex items-center justify-between">
                <div>
                  <h3 className="text-xl font-bold text-gray-900">{selectedDataSource.id}</h3>
                  <div className="flex items-center mt-2">
                    <span className="text-sm text-gray-500">Type: </span>
                    <span className="ml-2 px-2 py-1 bg-blue-100 text-blue-700 rounded text-sm font-medium">
                      {selectedDataSource.type}
                    </span>
                  </div>
                </div>
                <button
                  onClick={handleTestConnection}
                  disabled={testing}
                  className={`flex items-center px-4 py-2 rounded-lg font-medium transition-colors ${
                    testing
                      ? 'bg-gray-300 text-gray-500 cursor-not-allowed'
                      : 'bg-green-600 text-white hover:bg-green-700'
                  }`}
                >
                  {testing ? (
                    <>
                      <ArrowPathIcon className="w-4 h-4 mr-2 animate-spin" />
                      Testing...
                    </>
                  ) : (
                    <>
                      <CheckCircleIcon className="w-4 h-4 mr-2" />
                      Test Connection
                    </>
                  )}
                </button>
              </div>
            </div>

            {/* 测试结果 */}
            {testResult && (
              <div className={`p-4 rounded-lg border ${
                testResult.success
                  ? 'bg-green-50 border-green-200'
                  : 'bg-red-50 border-red-200'
              }`}>
                <div className="flex items-start">
                  {testResult.success ? (
                    <CheckCircleIcon className="w-5 h-5 text-green-600 mr-2 mt-0.5" />
                  ) : (
                    <XCircleIcon className="w-5 h-5 text-red-600 mr-2 mt-0.5" />
                  )}
                  <div className="flex-1">
                    <div className={`font-medium ${
                      testResult.success ? 'text-green-800' : 'text-red-800'
                    }`}>
                      {testResult.success ? 'Connection Successful' : 'Connection Failed'}
                    </div>
                    <div className={`text-sm mt-1 ${
                      testResult.success ? 'text-green-700' : 'text-red-700'
                    }`}>
                      {testResult.message}
                    </div>
                    {testResult.success && testResult.metadata && Object.keys(testResult.metadata).length > 0 && (
                      <div className="mt-3 pt-3 border-t border-green-200">
                        <div className="text-xs font-semibold text-green-800 mb-2">Database Information:</div>
                        <div className="space-y-1">
                          {Object.entries(testResult.metadata).map(([key, value]) => (
                            <div key={key} className="text-xs text-green-700">
                              <span className="font-medium">{key}:</span> {value}
                            </div>
                          ))}
                        </div>
                      </div>
                    )}
                  </div>
                </div>
              </div>
            )}

            <div className="grid grid-cols-2 gap-4">
              <div>
                <label className="text-sm font-medium text-gray-500">Host</label>
                <div className="mt-1 text-sm text-gray-900">{selectedDataSource.host}</div>
              </div>
              <div>
                <label className="text-sm font-medium text-gray-500">Port</label>
                <div className="mt-1 text-sm text-gray-900">{selectedDataSource.port}</div>
              </div>
              <div>
                <label className="text-sm font-medium text-gray-500">Database</label>
                <div className="mt-1 text-sm text-gray-900">{selectedDataSource.database}</div>
              </div>
              <div>
                <label className="text-sm font-medium text-gray-500">Username</label>
                <div className="mt-1 text-sm text-gray-900">{selectedDataSource.username}</div>
              </div>
            </div>

            <div>
              <label className="text-sm font-medium text-gray-500">JDBC URL</label>
              <div className="mt-1 p-2 bg-gray-50 rounded border border-gray-200">
                <code className="text-xs text-gray-700 break-all">{selectedDataSource.jdbc_url}</code>
              </div>
            </div>

            {selectedDataSource.properties && Object.keys(selectedDataSource.properties).length > 0 && (
              <div>
                <label className="text-sm font-medium text-gray-500">Properties</label>
                <div className="mt-1 p-2 bg-gray-50 rounded border border-gray-200">
                  <pre className="text-xs text-gray-700">
                    {JSON.stringify(selectedDataSource.properties, null, 2)}
                  </pre>
                </div>
              </div>
            )}

            <div className="pt-4 border-t border-gray-200">
              <h4 className="text-sm font-semibold text-gray-900 mb-2">Used by Object Types</h4>
              <div className="text-sm text-gray-500">
                {/* TODO: 显示使用该数据源的 ObjectType 列表 */}
                <p>Feature coming soon...</p>
              </div>
            </div>
          </div>
        ) : (
          <div className="text-center py-12 text-gray-500">
            <InformationCircleIcon className="w-12 h-12 mx-auto mb-2 text-gray-400" />
            <p>Select a data source to view details</p>
          </div>
        )}
      </div>
    </div>
  );
}

