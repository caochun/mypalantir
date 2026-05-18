package com.mypalantir.fee;

import com.mypalantir.config.Config;
import com.mypalantir.fee.pipeline.BuildGraphPipeline;
import com.mypalantir.fee.pipeline.ComputeFeesPipeline;
import com.mypalantir.fee.tool.FindPathTool;
import com.mypalantir.fee.validation.ValidatePathTool;
import com.mypalantir.reasoning.function.FunctionRegistry;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.stereotype.Service;

import jakarta.annotation.PostConstruct;
import java.io.BufferedReader;
import java.io.FileReader;
import java.io.IOException;
import java.sql.Connection;
import java.sql.DriverManager;
import java.sql.SQLException;
import java.sql.Statement;

@Service
public class FeeService {

    private static final Logger logger = LoggerFactory.getLogger(FeeService.class);

    private final Config config;
    private final FunctionRegistry functionRegistry;

    public FeeService(Config config, FunctionRegistry functionRegistry) {
        this.config = config;
        this.functionRegistry = functionRegistry;
    }

    @PostConstruct
    public void initialize() {
        if (!"fee".equals(config.getOntologyModel())) {
            logger.debug("Ontology model is '{}', skipping fee initialization", config.getOntologyModel());
            return;
        }

        String jdbcUrl = "jdbc:h2:file:./data/h2/mypalantir;AUTO_SERVER=TRUE";
        logger.info("Initializing Fee Rate Management model...");

        try {
            executeSqlScript(jdbcUrl, "scripts/fee/createTable_fee.sql");
            logger.info("Fee tables created successfully");
        } catch (Exception e) {
            logger.error("Failed to create fee tables", e);
            throw new RuntimeException("Failed to create fee tables", e);
        }

        try {
            FeeDataLoader loader = new FeeDataLoader();
            loader.loadAll(jdbcUrl, "data/fee");
            logger.info("Fee data loaded successfully");
        } catch (Exception e) {
            logger.error("Failed to load fee data", e);
            throw new RuntimeException("Failed to load fee data", e);
        }

        functionRegistry.register(new BuildGraphPipeline(jdbcUrl));
        functionRegistry.register(new ComputeFeesPipeline(jdbcUrl));
        functionRegistry.register(new FindPathTool(jdbcUrl));
        functionRegistry.register(new ValidatePathTool(jdbcUrl));
        logger.info("Fee pipeline functions registered: build_graph, compute_fees, find_path, validate_path");
    }

    private void executeSqlScript(String jdbcUrl, String scriptPath) throws SQLException, IOException {
        StringBuilder sql = new StringBuilder();
        try (BufferedReader reader = new BufferedReader(new FileReader(scriptPath))) {
            String line;
            while ((line = reader.readLine()) != null) {
                line = line.trim();
                if (line.startsWith("--") || line.isEmpty()) continue;
                sql.append(line).append(" ");
            }
        }

        try (Connection conn = DriverManager.getConnection(jdbcUrl, "sa", "");
             Statement stmt = conn.createStatement()) {
            for (String s : sql.toString().split(";")) {
                String trimmed = s.trim();
                if (!trimmed.isEmpty()) {
                    stmt.execute(trimmed);
                }
            }
        }
    }
}
