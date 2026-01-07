package com.mypalantir.query;

import com.mypalantir.meta.Loader;
import java.util.HashMap;
import java.util.Map;
import java.util.List;
import java.util.ArrayList;

public class QueryDebugTest {
    public static void main(String[] args) throws Exception {
        // 加载 schema
        Loader loader = new Loader("./ontology/schema.yaml");
        loader.load();
        
        // 创建查询
        Map<String, Object> queryMap = new HashMap<>();
        queryMap.put("from", "车辆");
        
        List<String> select = new ArrayList<>();
        select.add("车牌号");
        select.add("车辆类型");
        queryMap.put("select", select);
        
        List<Map<String, Object>> links = new ArrayList<>();
        Map<String, Object> linkQuery = new HashMap<>();
        linkQuery.put("name", "持有");
        List<String> linkSelect = new ArrayList<>();
        linkSelect.add("介质编号");
        linkSelect.add("介质类型");
        linkQuery.put("select", linkSelect);
        links.add(linkQuery);
        queryMap.put("links", links);
        
        queryMap.put("limit", 10);
        
        // 解析查询
        QueryParser parser = new QueryParser();
        OntologyQuery query = parser.parseMap(queryMap);
        
        System.out.println("=== Parsed OntologyQuery ===");
        System.out.println("From: " + query.getFrom());
        System.out.println("Select: " + query.getSelect());
        if (query.getLinks() != null && !query.getLinks().isEmpty()) {
            System.out.println("Links:");
            for (OntologyQuery.LinkQuery lq : query.getLinks()) {
                System.out.println("  - Name: " + lq.getName());
                System.out.println("    Select: " + lq.getSelect());
            }
        }
        System.out.println("Limit: " + query.getLimit());
        System.out.println("============================");
        
        // 构建 RelNode
        RelNodeBuilder builder = new RelNodeBuilder(loader);
        builder.initialize();
        
        try {
            org.apache.calcite.rel.RelNode relNode = builder.buildRelNode(query);
            System.out.println("\n=== RelNode Built Successfully ===");
            System.out.println("RelNode type: " + relNode.getClass().getSimpleName());
        } catch (Exception e) {
            System.err.println("\n=== Error Building RelNode ===");
            e.printStackTrace();
        }
    }
}






