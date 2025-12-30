import axios from 'axios';

// 如果设置了环境变量则使用，否则使用相对路径（同源）
const API_BASE_URL = import.meta.env.VITE_API_BASE_URL || '/api/v1';

const apiClient = axios.create({
  baseURL: API_BASE_URL,
  headers: {
    'Content-Type': 'application/json',
  },
});

// 类型定义（匹配后端返回的小写字段名）
export interface ObjectType {
  name: string;
  description: string;
  base_type: string | null;
  properties: Property[];
  data_source?: DataSourceMapping;  // 数据源映射配置（可选）
}

export interface Property {
  name: string;
  data_type: string;
  required: boolean;
  description: string;
  default_value: any;
  constraints: Record<string, any> | null;
}

export interface LinkType {
  name: string;
  description: string;
  source_type: string;
  target_type: string;
  cardinality: string;
  direction: string;
  properties: Property[];
}

export interface DataSourceConfig {
  id: string;
  type: string;
  host: string;
  port: number;
  database: string;
  username: string;
  password?: string;
  jdbc_url: string;
  properties?: Record<string, any>;
}

export interface DataSourceMapping {
  connection_id: string;
  table: string;
  id_column: string;
  field_mapping: Record<string, string>;
}

export interface Instance {
  id: string;
  [key: string]: any;
}

export interface Link {
  id: string;
  source_id: string;
  target_id: string;
  [key: string]: any;
}

export interface ApiResponse<T> {
  code: number;
  message: string;
  data: T;
  timestamp: string;
}

// Schema API
export const schemaApi = {
  getObjectTypes: async (): Promise<ObjectType[]> => {
    const response = await apiClient.get<ApiResponse<ObjectType[]>>('/schema/object-types');
    return response.data.data;
  },

  getObjectType: async (name: string): Promise<ObjectType> => {
    const response = await apiClient.get<ApiResponse<ObjectType>>(`/schema/object-types/${name}`);
    return response.data.data;
  },

  getObjectTypeProperties: async (name: string): Promise<Property[]> => {
    const response = await apiClient.get<ApiResponse<Property[]>>(`/schema/object-types/${name}/properties`);
    return response.data.data;
  },

  getLinkTypes: async (): Promise<LinkType[]> => {
    const response = await apiClient.get<ApiResponse<LinkType[]>>('/schema/link-types');
    return response.data.data;
  },

  getLinkType: async (name: string): Promise<LinkType> => {
    const response = await apiClient.get<ApiResponse<LinkType>>(`/schema/link-types/${name}`);
    return response.data.data;
  },

  getOutgoingLinks: async (objectTypeName: string): Promise<LinkType[]> => {
    const response = await apiClient.get<ApiResponse<LinkType[]>>(`/schema/object-types/${objectTypeName}/outgoing-links`);
    return response.data.data;
  },

  getIncomingLinks: async (objectTypeName: string): Promise<LinkType[]> => {
    const response = await apiClient.get<ApiResponse<LinkType[]>>(`/schema/object-types/${objectTypeName}/incoming-links`);
    return response.data.data;
  },

  getDataSources: async (): Promise<DataSourceConfig[]> => {
    const response = await apiClient.get<ApiResponse<DataSourceConfig[]>>('/schema/data-sources');
    return response.data.data;
  },

  getDataSource: async (id: string): Promise<DataSourceConfig> => {
    const response = await apiClient.get<ApiResponse<DataSourceConfig>>(`/schema/data-sources/${id}`);
    return response.data.data;
  },

  testConnection: async (id: string): Promise<{ success: boolean; message: string; metadata?: Record<string, string> }> => {
    const response = await apiClient.post<ApiResponse<{ success: boolean; message: string; metadata?: Record<string, string> }>>(
      `/schema/data-sources/${id}/test`
    );
    return response.data.data;
  },
};

// Instance API
export const instanceApi = {
  create: async (objectType: string, data: Record<string, any>): Promise<string> => {
    const response = await apiClient.post<ApiResponse<{ id: string }>>(`/instances/${objectType}`, data);
    return response.data.data.id;
  },

  list: async (objectType: string, offset = 0, limit = 20, filters?: Record<string, any>): Promise<{ items: Instance[]; total: number }> => {
    const params = new URLSearchParams({
      offset: offset.toString(),
      limit: limit.toString(),
      ...filters,
    });
    const response = await apiClient.get<ApiResponse<{ items: Instance[]; total: number; offset: number; limit: number }>>(
      `/instances/${objectType}?${params}`
    );
    return response.data.data;
  },

  get: async (objectType: string, id: string): Promise<Instance> => {
    const response = await apiClient.get<ApiResponse<Instance>>(`/instances/${objectType}/${id}`);
    return response.data.data;
  },

  update: async (objectType: string, id: string, data: Record<string, any>): Promise<void> => {
    await apiClient.put(`/instances/${objectType}/${id}`, data);
  },

  delete: async (objectType: string, id: string): Promise<void> => {
    await apiClient.delete(`/instances/${objectType}/${id}`);
  },
};

// Link API
export const linkApi = {
  create: async (linkType: string, sourceId: string, targetId: string, properties?: Record<string, any>): Promise<string> => {
    const response = await apiClient.post<ApiResponse<{ id: string }>>(`/links/${linkType}`, {
      source_id: sourceId,
      target_id: targetId,
      properties: properties || {},
    });
    return response.data.data.id;
  },

  list: async (linkType: string, offset = 0, limit = 20): Promise<{ items: Link[]; total: number }> => {
    const params = new URLSearchParams({
      offset: offset.toString(),
      limit: limit.toString(),
    });
    const response = await apiClient.get<ApiResponse<{ items: Link[]; total: number; offset: number; limit: number }>>(
      `/links/${linkType}?${params}`
    );
    return response.data.data;
  },

  get: async (linkType: string, id: string): Promise<Link> => {
    const response = await apiClient.get<ApiResponse<Link>>(`/links/${linkType}/${id}`);
    return response.data.data;
  },

  update: async (linkType: string, id: string, properties: Record<string, any>): Promise<void> => {
    await apiClient.put(`/links/${linkType}/${id}`, properties);
  },

  delete: async (linkType: string, id: string): Promise<void> => {
    await apiClient.delete(`/links/${linkType}/${id}`);
  },

  getInstanceLinks: async (objectType: string, instanceId: string, linkType: string): Promise<Link[]> => {
    const response = await apiClient.get<ApiResponse<Link[]>>(`/instances/${objectType}/${instanceId}/links/${linkType}`);
    return response.data.data;
  },

  getConnectedInstances: async (objectType: string, instanceId: string, linkType: string, direction = 'outgoing'): Promise<Instance[]> => {
    const response = await apiClient.get<ApiResponse<Instance[]>>(
      `/instances/${objectType}/${instanceId}/connected/${linkType}?direction=${direction}`
    );
    return response.data.data;
  },
};

export default apiClient;

