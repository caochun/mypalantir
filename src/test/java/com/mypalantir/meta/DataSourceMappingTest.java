package com.mypalantir.meta;

import com.fasterxml.jackson.databind.ObjectMapper;
import com.fasterxml.jackson.dataformat.yaml.YAMLFactory;
import java.io.IOException;

public class DataSourceMappingTest {
    public static void main(String[] args) {
        String schemaPath = "./ontology/schema.yaml";
        
        try {
            Parser parser = new Parser(schemaPath);
            OntologySchema schema = parser.parse();
            
            System.out.println("=== 数据源配置测试 ===\n");
            
            // 检查数据源配置
            if (schema.getDataSources() != null && !schema.getDataSources().isEmpty()) {
                System.out.println("数据源数量: " + schema.getDataSources().size());
                for (DataSourceConfig ds : schema.getDataSources()) {
                    System.out.println("\n数据源 ID: " + ds.getId());
                    System.out.println("  类型: " + ds.getType());
                    System.out.println("  主机: " + ds.getHost());
                    System.out.println("  端口: " + ds.getPort());
                    System.out.println("  数据库: " + ds.getDatabase());
                    System.out.println("  JDBC URL: " + ds.buildJdbcUrl());
                }
            } else {
                System.out.println("未配置数据源（使用文件系统存储）");
            }
            
            // 检查 ObjectType 的数据源映射
            System.out.println("\n=== ObjectType 数据源映射 ===\n");
            int withDataSource = 0;
            int withoutDataSource = 0;
            
            for (ObjectType ot : schema.getObjectTypes()) {
                if (ot.hasDataSource()) {
                    withDataSource++;
                    DataSourceMapping mapping = ot.getDataSource();
                    System.out.println("ObjectType: " + ot.getName());
                    System.out.println("  数据源连接: " + mapping.getConnectionId());
                    System.out.println("  表名: " + mapping.getTable());
                    System.out.println("  ID 列: " + mapping.getIdColumn());
                    System.out.println("  字段映射数量: " + 
                        (mapping.getFieldMapping() != null ? mapping.getFieldMapping().size() : 0));
                    if (mapping.getFieldMapping() != null) {
                        System.out.println("  字段映射:");
                        mapping.getFieldMapping().forEach((prop, col) -> 
                            System.out.println("    " + prop + " -> " + col));
                    }
                    System.out.println();
                } else {
                    withoutDataSource++;
                }
            }
            
            System.out.println("有数据源配置的 ObjectType: " + withDataSource);
            System.out.println("无数据源配置的 ObjectType: " + withoutDataSource + " (使用文件系统存储)");
            
        } catch (IOException e) {
            System.err.println("解析失败: " + e.getMessage());
            e.printStackTrace();
        }
    }
}

