package com.mypalantir.controller;

import com.mypalantir.meta.DataSourceConfig;
import com.mypalantir.meta.LinkType;
import com.mypalantir.meta.Loader;
import com.mypalantir.meta.ObjectType;
import com.mypalantir.meta.Property;
import com.mypalantir.service.DataSourceTestService;
import com.mypalantir.service.SchemaService;
import org.springframework.http.HttpStatus;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.*;

import java.util.HashMap;
import java.util.List;
import java.util.Map;

@RestController
@RequestMapping("/api/v1/schema")
public class SchemaController {
    private final SchemaService schemaService;
    private final DataSourceTestService testService;

    public SchemaController(SchemaService schemaService, DataSourceTestService testService) {
        this.schemaService = schemaService;
        this.testService = testService;
    }

    @GetMapping("/object-types")
    public ResponseEntity<ApiResponse<List<ObjectType>>> listObjectTypes() {
        List<ObjectType> objectTypes = schemaService.listObjectTypes();
        return ResponseEntity.ok(ApiResponse.success(objectTypes));
    }

    @GetMapping("/object-types/{name}")
    public ResponseEntity<ApiResponse<ObjectType>> getObjectType(@PathVariable String name) {
        try {
            ObjectType objectType = schemaService.getObjectType(name);
            return ResponseEntity.ok(ApiResponse.success(objectType));
        } catch (Loader.NotFoundException e) {
            return ResponseEntity.status(HttpStatus.NOT_FOUND)
                .body(ApiResponse.error(404, e.getMessage()));
        }
    }

    @GetMapping("/object-types/{name}/properties")
    public ResponseEntity<ApiResponse<List<Property>>> getObjectTypeProperties(@PathVariable String name) {
        try {
            List<Property> properties = schemaService.getObjectTypeProperties(name);
            return ResponseEntity.ok(ApiResponse.success(properties));
        } catch (Loader.NotFoundException e) {
            return ResponseEntity.status(HttpStatus.NOT_FOUND)
                .body(ApiResponse.error(404, e.getMessage()));
        }
    }

    @GetMapping("/object-types/{name}/outgoing-links")
    public ResponseEntity<ApiResponse<List<LinkType>>> getOutgoingLinks(@PathVariable String name) {
        List<LinkType> links = schemaService.getOutgoingLinks(name);
        return ResponseEntity.ok(ApiResponse.success(links));
    }

    @GetMapping("/object-types/{name}/incoming-links")
    public ResponseEntity<ApiResponse<List<LinkType>>> getIncomingLinks(@PathVariable String name) {
        List<LinkType> links = schemaService.getIncomingLinks(name);
        return ResponseEntity.ok(ApiResponse.success(links));
    }

    @GetMapping("/link-types")
    public ResponseEntity<ApiResponse<List<LinkType>>> listLinkTypes() {
        List<LinkType> linkTypes = schemaService.listLinkTypes();
        return ResponseEntity.ok(ApiResponse.success(linkTypes));
    }

    @GetMapping("/link-types/{name}")
    public ResponseEntity<ApiResponse<LinkType>> getLinkType(@PathVariable String name) {
        try {
            LinkType linkType = schemaService.getLinkType(name);
            return ResponseEntity.ok(ApiResponse.success(linkType));
        } catch (Loader.NotFoundException e) {
            return ResponseEntity.status(HttpStatus.NOT_FOUND)
                .body(ApiResponse.error(404, e.getMessage()));
        }
    }

    @GetMapping("/data-sources")
    public ResponseEntity<ApiResponse<List<DataSourceConfig>>> listDataSources() {
        List<DataSourceConfig> dataSources = schemaService.listDataSources();
        return ResponseEntity.ok(ApiResponse.success(dataSources));
    }

    @GetMapping("/data-sources/{id}")
    public ResponseEntity<ApiResponse<DataSourceConfig>> getDataSource(@PathVariable String id) {
        try {
            DataSourceConfig dataSource = schemaService.getDataSourceById(id);
            return ResponseEntity.ok(ApiResponse.success(dataSource));
        } catch (Loader.NotFoundException e) {
            return ResponseEntity.status(HttpStatus.NOT_FOUND)
                .body(ApiResponse.error(404, e.getMessage()));
        }
    }

    @PostMapping("/data-sources/{id}/test")
    public ResponseEntity<ApiResponse<Map<String, Object>>> testConnection(@PathVariable String id) {
        try {
            DataSourceTestService.TestResult result = testService.testConnection(id);
            
            Map<String, Object> response = new HashMap<>();
            response.put("success", result.isSuccess());
            response.put("message", result.getMessage());
            if (result.getMetadata() != null && !result.getMetadata().isEmpty()) {
                response.put("metadata", result.getMetadata());
            }
            
            if (result.isSuccess()) {
                return ResponseEntity.ok(ApiResponse.success(response));
            } else {
                return ResponseEntity.status(HttpStatus.BAD_REQUEST)
                    .body(ApiResponse.error(400, result.getMessage()));
            }
        } catch (Exception e) {
            return ResponseEntity.status(HttpStatus.INTERNAL_SERVER_ERROR)
                .body(ApiResponse.error(500, "Test failed: " + e.getMessage()));
        }
    }
}

