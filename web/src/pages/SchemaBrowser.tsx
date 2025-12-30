import { useEffect, useState } from 'react';
import type { ObjectType, LinkType, DataSourceConfig } from '../api/client';
import { schemaApi } from '../api/client';
import { 
  CubeIcon, 
  LinkIcon,
  InformationCircleIcon,
  ServerIcon,
  CheckCircleIcon,
  XCircleIcon,
  ArrowPathIcon
} from '@heroicons/react/24/outline';

export default function SchemaBrowser() {
  const [objectTypes, setObjectTypes] = useState<ObjectType[]>([]);
  const [linkTypes, setLinkTypes] = useState<LinkType[]>([]);
  const [dataSources, setDataSources] = useState<DataSourceConfig[]>([]);
  const [selectedObjectType, setSelectedObjectType] = useState<ObjectType | null>(null);
  const [selectedLinkType, setSelectedLinkType] = useState<LinkType | null>(null);
  const [activeTab, setActiveTab] = useState<'properties' | 'datasource'>('properties');
  const [loading, setLoading] = useState(true);
  const [testing, setTesting] = useState(false);
  const [testResult, setTestResult] = useState<{ success: boolean; message: string; metadata?: Record<string, string> } | null>(null);

  useEffect(() => {
    const loadData = async () => {
      try {
        const [objectTypesData, linkTypesData, dataSourcesData] = await Promise.all([
          schemaApi.getObjectTypes(),
          schemaApi.getLinkTypes(),
          schemaApi.getDataSources(),
        ]);
        setObjectTypes(objectTypesData);
        setLinkTypes(linkTypesData);
        setDataSources(dataSourcesData);
        if (objectTypesData.length > 0) {
          setSelectedObjectType(objectTypesData[0]);
        }
      } catch (error) {
        console.error('Failed to load schema:', error);
      } finally {
        setLoading(false);
      }
    };
    loadData();
  }, []);

  // 当选择的对象类型改变时，重置 Tab 和测试结果
  useEffect(() => {
    setActiveTab('properties');
    setTestResult(null);
  }, [selectedObjectType?.name]);

  // 获取数据源配置详情
  const getDataSourceConfig = (connectionId: string): DataSourceConfig | undefined => {
    return dataSources.find(ds => ds.id === connectionId);
  };

  // 测试数据源连接
  const handleTestConnection = async (connectionId: string) => {
    try {
      setTesting(true);
      setTestResult(null);
      const result = await schemaApi.testConnection(connectionId);
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

  if (loading) {
    return <div className="text-center py-12">Loading...</div>;
  }

  return (
    <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
      {/* Object Types List */}
      <div className="bg-white rounded-lg shadow-sm border border-gray-200 p-4">
        <h2 className="text-lg font-semibold text-gray-900 mb-4 flex items-center">
          <CubeIcon className="w-5 h-5 mr-2" />
          Object Types ({objectTypes.length})
        </h2>
        <div className="space-y-2">
          {objectTypes.map((ot) => (
            <button
              key={ot.name}
              onClick={() => {
                setSelectedObjectType(ot);
                setSelectedLinkType(null);
              }}
              className={`w-full text-left px-3 py-2 rounded-lg transition-colors ${
                selectedObjectType?.name === ot.name
                  ? 'bg-blue-50 text-blue-700 border border-blue-200'
                  : 'hover:bg-gray-50 text-gray-700 border border-transparent'
              }`}
            >
              <div className="flex items-center justify-between">
                <div className="font-medium">{ot.name}</div>
                {ot.data_source && (
                  <ServerIcon 
                    className="w-4 h-4 text-green-600" 
                    title="Has data source configured"
                  />
                )}
              </div>
              {ot.description && (
                <div className="text-sm text-gray-500 mt-1">{ot.description}</div>
              )}
            </button>
          ))}
        </div>
      </div>

      {/* Object Type Details */}
      <div className="bg-white rounded-lg shadow-sm border border-gray-200 p-4">
        <h2 className="text-lg font-semibold text-gray-900 mb-4">Object Type Details</h2>
        {selectedObjectType ? (
          <div>
            <div className="mb-4">
              <h3 className="text-xl font-bold text-gray-900">{selectedObjectType.name}</h3>
              {selectedObjectType.description && (
                <p className="text-gray-600 mt-1">{selectedObjectType.description}</p>
              )}
            </div>

            {/* Tab 切换 */}
            <div className="border-b border-gray-200 mb-4">
              <nav className="flex space-x-4">
                <button
                  onClick={() => setActiveTab('properties')}
                  className={`py-2 px-1 border-b-2 font-medium text-sm ${
                    activeTab === 'properties'
                      ? 'border-blue-500 text-blue-600'
                      : 'border-transparent text-gray-500 hover:text-gray-700'
                  }`}
                >
                  Properties
                </button>
                <button
                  onClick={() => setActiveTab('datasource')}
                  className={`py-2 px-1 border-b-2 font-medium text-sm flex items-center ${
                    activeTab === 'datasource'
                      ? 'border-blue-500 text-blue-600'
                      : 'border-transparent text-gray-500 hover:text-gray-700'
                  }`}
                >
                  <ServerIcon className="w-4 h-4 mr-1" />
                  Data Source
                </button>
              </nav>
            </div>

            {/* Tab 内容 */}
            {activeTab === 'properties' ? (
              <div className="mb-4">
                <h4 className="font-semibold text-gray-900 mb-2">Properties</h4>
                <div className="space-y-2">
                  {selectedObjectType.properties.map((prop) => (
                    <div
                      key={prop.name}
                      className="p-3 bg-gray-50 rounded-lg border border-gray-200"
                    >
                      <div className="flex items-center justify-between">
                        <span className="font-medium text-gray-900">{prop.name}</span>
                        <span className="text-xs px-2 py-1 bg-blue-100 text-blue-700 rounded">
                          {prop.data_type}
                        </span>
                      </div>
                      {prop.description && (
                        <p className="text-sm text-gray-600 mt-1">{prop.description}</p>
                      )}
                      <div className="flex items-center gap-2 mt-2">
                        {prop.required && (
                          <span className="text-xs px-2 py-1 bg-red-100 text-red-700 rounded">
                            Required
                          </span>
                        )}
                        {prop.default_value !== null && prop.default_value !== undefined && (
                          <span className="text-xs text-gray-500">
                            Default: {JSON.stringify(prop.default_value)}
                          </span>
                        )}
                      </div>
                      {prop.constraints && Object.keys(prop.constraints).length > 0 && (
                        <div className="mt-2 text-xs text-gray-500">
                          Constraints: {JSON.stringify(prop.constraints)}
                        </div>
                      )}
                    </div>
                  ))}
                </div>
              </div>
            ) : (
              <div className="mb-4">
                {selectedObjectType.data_source ? (
                  <div className="space-y-4">
                    {/* 数据源配置信息 */}
                    <div className="p-4 bg-blue-50 rounded-lg border border-blue-200">
                      <div className="flex items-center justify-between mb-3">
                        <h4 className="font-semibold text-gray-900 flex items-center">
                          <ServerIcon className="w-5 h-5 mr-2 text-blue-600" />
                          Data Source Configuration
                        </h4>
                        {(() => {
                          const dsConfig = getDataSourceConfig(selectedObjectType.data_source!.connection_id);
                          return dsConfig ? (
                            <button
                              onClick={() => handleTestConnection(selectedObjectType.data_source!.connection_id)}
                              disabled={testing}
                              className={`flex items-center px-3 py-1 text-sm rounded-lg font-medium transition-colors ${
                                testing
                                  ? 'bg-gray-300 text-gray-500 cursor-not-allowed'
                                  : 'bg-green-600 text-white hover:bg-green-700'
                              }`}
                            >
                              {testing ? (
                                <>
                                  <ArrowPathIcon className="w-4 h-4 mr-1 animate-spin" />
                                  Testing...
                                </>
                              ) : (
                                <>
                                  <CheckCircleIcon className="w-4 h-4 mr-1" />
                                  Test Connection
                                </>
                              )}
                            </button>
                          ) : null;
                        })()}
                      </div>
                      
                      <div className="space-y-2 text-sm">
                        <div>
                          <span className="text-gray-600">Connection ID:</span>{' '}
                          <span className="font-medium">{selectedObjectType.data_source.connection_id}</span>
                        </div>
                        <div>
                          <span className="text-gray-600">Table:</span>{' '}
                          <span className="font-medium">{selectedObjectType.data_source.table}</span>
                        </div>
                        <div>
                          <span className="text-gray-600">ID Column:</span>{' '}
                          <span className="font-medium">{selectedObjectType.data_source.id_column}</span>
                        </div>
                      </div>

                      {/* 数据源详细信息 */}
                      {(() => {
                        const dsConfig = getDataSourceConfig(selectedObjectType.data_source.connection_id);
                        if (dsConfig) {
                          return (
                            <div className="mt-4 pt-4 border-t border-blue-200">
                              <div className="text-xs font-semibold text-gray-700 mb-2">Connection Details:</div>
                              <div className="space-y-1 text-xs">
                                <div>
                                  <span className="text-gray-600">Type:</span>{' '}
                                  <span className="font-medium">{dsConfig.type}</span>
                                </div>
                                <div>
                                  <span className="text-gray-600">Host:</span>{' '}
                                  <span className="font-medium">{dsConfig.host}</span>
                                </div>
                                {dsConfig.port > 0 && (
                                  <div>
                                    <span className="text-gray-600">Port:</span>{' '}
                                    <span className="font-medium">{dsConfig.port}</span>
                                  </div>
                                )}
                                <div>
                                  <span className="text-gray-600">Database:</span>{' '}
                                  <span className="font-medium">{dsConfig.database}</span>
                                </div>
                              </div>
                            </div>
                          );
                        }
                        return null;
                      })()}
                    </div>

                    {/* 字段映射 */}
                    <div className="p-4 bg-gray-50 rounded-lg border border-gray-200">
                      <h4 className="font-semibold text-gray-900 mb-3">Field Mapping</h4>
                      <div className="space-y-2">
                        {Object.entries(selectedObjectType.data_source.field_mapping || {}).map(([propertyName, columnName]) => (
                          <div key={propertyName} className="flex items-center justify-between p-2 bg-white rounded border border-gray-200">
                            <span className="text-sm font-medium text-gray-900">{propertyName}</span>
                            <span className="text-sm text-gray-500">→</span>
                            <code className="text-xs px-2 py-1 bg-gray-100 text-gray-700 rounded">{columnName}</code>
                          </div>
                        ))}
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
                  </div>
                ) : (
                  <div className="p-4 bg-gray-50 rounded-lg border border-gray-200">
                    <div className="flex items-center justify-between">
                      <div>
                        <h4 className="font-semibold text-gray-900 mb-1 flex items-center">
                          <InformationCircleIcon className="w-5 h-5 mr-2 text-gray-400" />
                          No Data Source Configured
                        </h4>
                        <p className="text-sm text-gray-500">This object type uses file system storage</p>
                      </div>
                    </div>
                    <div className="mt-3 text-xs text-gray-500">
                      <p>To configure a data source, edit the schema.yaml file and add a data_source mapping for this object type.</p>
                    </div>
                  </div>
                )}
              </div>
            )}
          </div>
        ) : (
          <div className="text-center py-8 text-gray-500">
            <InformationCircleIcon className="w-12 h-12 mx-auto mb-2 text-gray-400" />
            <p>Select an object type to view details</p>
          </div>
        )}
      </div>

      {/* Link Types */}
      <div className="bg-white rounded-lg shadow-sm border border-gray-200 p-4">
        <h2 className="text-lg font-semibold text-gray-900 mb-4 flex items-center">
          <LinkIcon className="w-5 h-5 mr-2" />
          Link Types ({linkTypes.length})
        </h2>
        <div className="space-y-2">
          {linkTypes.map((lt) => (
            <button
              key={lt.name}
              onClick={() => {
                setSelectedLinkType(lt);
                setSelectedObjectType(null);
              }}
              className={`w-full text-left px-3 py-2 rounded-lg transition-colors ${
                selectedLinkType?.name === lt.name
                  ? 'bg-blue-50 text-blue-700 border border-blue-200'
                  : 'hover:bg-gray-50 text-gray-700 border border-transparent'
              }`}
            >
              <div className="font-medium">{lt.name}</div>
              <div className="text-sm text-gray-500 mt-1">
                {lt.source_type} → {lt.target_type}
              </div>
              {lt.description && (
                <div className="text-xs text-gray-400 mt-1">{lt.description}</div>
              )}
            </button>
          ))}
        </div>

        {selectedLinkType && (
          <div className="mt-4 p-3 bg-gray-50 rounded-lg border border-gray-200">
            <h4 className="font-semibold text-gray-900 mb-2">{selectedLinkType.name}</h4>
            <div className="text-sm space-y-1">
              <div>
                <span className="text-gray-600">Source:</span>{' '}
                <span className="font-medium">{selectedLinkType.source_type}</span>
              </div>
              <div>
                <span className="text-gray-600">Target:</span>{' '}
                <span className="font-medium">{selectedLinkType.target_type}</span>
              </div>
              <div>
                <span className="text-gray-600">Cardinality:</span>{' '}
                <span className="font-medium">{selectedLinkType.cardinality}</span>
              </div>
              <div>
                <span className="text-gray-600">Direction:</span>{' '}
                <span className="font-medium">{selectedLinkType.direction}</span>
              </div>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}

