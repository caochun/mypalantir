package com.mypalantir.service;

import com.mypalantir.meta.Loader;
import com.mypalantir.query.OntologyQuery;
import com.mypalantir.query.QueryExecutor;
import com.mypalantir.query.QueryParser;
import org.springframework.stereotype.Service;

import java.util.Map;

/**
 * 查询服务
 */
@Service
public class QueryService {
    private final Loader loader;
    private final QueryParser parser;
    private QueryExecutor executor;

    public QueryService(Loader loader) {
        this.loader = loader;
        this.parser = new QueryParser();
    }

    /**
     * 执行查询
     */
    public QueryExecutor.QueryResult executeQuery(Map<String, Object> queryMap) throws Exception {
        // 解析查询
        OntologyQuery query = parser.parseMap(queryMap);
        
        // 验证查询
        validateQuery(query);
        
        // 执行查询
        if (executor == null) {
            executor = new QueryExecutor(loader);
            executor.initialize();
        }
        
        return executor.execute(query);
    }

    /**
     * 验证查询
     */
    private void validateQuery(OntologyQuery query) throws Exception {
        if (query.getFrom() == null || query.getFrom().isEmpty()) {
            throw new IllegalArgumentException("Query must specify 'from' object type");
        }
        
        // 验证对象类型是否存在
        try {
            loader.getObjectType(query.getFrom());
        } catch (Loader.NotFoundException e) {
            throw new IllegalArgumentException("Object type '" + query.getFrom() + "' not found");
        }
    }
}

