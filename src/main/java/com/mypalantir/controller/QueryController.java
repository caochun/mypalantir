package com.mypalantir.controller;

import com.mypalantir.query.QueryExecutor;
import com.mypalantir.service.QueryService;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.*;

import java.util.Map;

/**
 * 查询控制器
 */
@RestController
@RequestMapping("/api/v1/query")
public class QueryController {
    private final QueryService queryService;

    public QueryController(QueryService queryService) {
        this.queryService = queryService;
    }

    /**
     * 执行查询
     * 接受 JSON 格式的查询请求
     */
    @PostMapping
    public ResponseEntity<ApiResponse<Map<String, Object>>> executeQuery(@RequestBody Map<String, Object> queryRequest) {
        try {
            QueryExecutor.QueryResult result = queryService.executeQuery(queryRequest);
            
            Map<String, Object> response = new java.util.HashMap<>();
            response.put("columns", result.getColumns());
            response.put("rows", result.getRows());
            response.put("rowCount", result.getRowCount());
            
            return ResponseEntity.ok(ApiResponse.success(response));
        } catch (IllegalArgumentException e) {
            return ResponseEntity.badRequest()
                .body(ApiResponse.error(400, e.getMessage()));
        } catch (Exception e) {
            return ResponseEntity.status(500)
                .body(ApiResponse.error(500, "Query execution failed: " + e.getMessage()));
        }
    }
}

