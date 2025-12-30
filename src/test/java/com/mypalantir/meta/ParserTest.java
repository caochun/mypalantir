package com.mypalantir.meta;

import com.fasterxml.jackson.databind.ObjectMapper;
import com.fasterxml.jackson.dataformat.yaml.YAMLFactory;
import java.io.IOException;

public class ParserTest {
    public static void main(String[] args) {
        String schemaPath = "./ontology/schema.yaml";
        
        try {
            // 创建 Parser 并解析
            Parser parser = new Parser(schemaPath);
            OntologySchema schema = parser.parse();
            
            // 使用 YAML 格式输出，便于查看
            ObjectMapper yamlMapper = new ObjectMapper(new YAMLFactory());
            String yamlOutput = yamlMapper.writerWithDefaultPrettyPrinter().writeValueAsString(schema);
            
            System.out.println("=== 解析 schema.yaml 得到的 OntologySchema 对象 ===\n");
            System.out.println(yamlOutput);
            
            // 输出统计信息
            System.out.println("\n=== 统计信息 ===");
            System.out.println("Version: " + schema.getVersion());
            System.out.println("Namespace: " + schema.getNamespace());
            System.out.println("Object Types 数量: " + 
                (schema.getObjectTypes() != null ? schema.getObjectTypes().size() : 0));
            System.out.println("Link Types 数量: " + 
                (schema.getLinkTypes() != null ? schema.getLinkTypes().size() : 0));
            
            // 输出 Object Types 列表
            if (schema.getObjectTypes() != null && !schema.getObjectTypes().isEmpty()) {
                System.out.println("\n=== Object Types 列表 ===");
                for (ObjectType ot : schema.getObjectTypes()) {
                    System.out.println("- " + ot.getName() + 
                        " (属性数: " + 
                        (ot.getProperties() != null ? ot.getProperties().size() : 0) + ")");
                }
            }
            
            // 输出 Link Types 列表
            if (schema.getLinkTypes() != null && !schema.getLinkTypes().isEmpty()) {
                System.out.println("\n=== Link Types 列表 ===");
                for (LinkType lt : schema.getLinkTypes()) {
                    System.out.println("- " + lt.getName() + 
                        " (" + lt.getSourceType() + " -> " + lt.getTargetType() + 
                        ", 属性数: " + 
                        (lt.getProperties() != null ? lt.getProperties().size() : 0) + ")");
                }
            }
            
        } catch (IOException e) {
            System.err.println("解析失败: " + e.getMessage());
            e.printStackTrace();
        }
    }
}

