package com.mypalantir;

import com.mypalantir.config.Config;
import com.mypalantir.config.EnvConfig;
import com.mypalantir.meta.Loader;
import com.mypalantir.meta.Validator;
import com.mypalantir.service.DataValidator;
import com.mypalantir.service.InstanceService;
import com.mypalantir.service.LinkService;
import com.mypalantir.service.QueryService;
import com.mypalantir.service.SchemaService;
import com.mypalantir.repository.InstanceStorage;
import com.mypalantir.repository.LinkStorage;
import com.mypalantir.repository.PathManager;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.boot.SpringApplication;
import org.springframework.boot.autoconfigure.SpringBootApplication;
import org.springframework.boot.context.properties.EnableConfigurationProperties;
import org.springframework.context.annotation.Bean;

import java.io.IOException;

@SpringBootApplication
@EnableConfigurationProperties(Config.class)
public class MyPalantirApplication {
    private static final Logger logger = LoggerFactory.getLogger(MyPalantirApplication.class);

    public static void main(String[] args) {
        SpringApplication app = new SpringApplication(MyPalantirApplication.class);
        // 注册 .env 文件加载器
        app.addListeners(new EnvConfig());
        app.run(args);
    }

    @Bean
    public Loader schemaLoader(Config config) {
        String filePath = config.getSchemaFilePath();
        String modelId = config.getOntologyModel();
        Loader loader = new Loader(filePath);
        try {
            loader.load();
            logger.info("Ontology model '{}' loaded successfully from: {} ({} object types, {} link types)", 
                modelId,
                filePath,
                loader.getSchema() != null && loader.getSchema().getObjectTypes() != null ? loader.getSchema().getObjectTypes().size() : 0,
                loader.getSchema() != null && loader.getSchema().getLinkTypes() != null ? loader.getSchema().getLinkTypes().size() : 0);
        } catch (IOException | Validator.ValidationException e) {
            logger.error("Failed to load ontology model '{}' from: {}", modelId, filePath, e);
            throw new RuntimeException("Failed to load schema", e);
        }
        return loader;
    }

    @Bean
    public PathManager pathManager(Config config, Loader loader) {
        String namespace = loader.getSchema() != null && loader.getSchema().getNamespace() != null
            ? loader.getSchema().getNamespace()
            : "default";
        return new PathManager(config.getDataRootPath(), namespace);
    }

    @Bean
    public InstanceStorage instanceStorage(PathManager pathManager) {
        return new InstanceStorage(pathManager);
    }

    @Bean
    public LinkStorage linkStorage(PathManager pathManager) {
        return new LinkStorage(pathManager);
    }

    @Bean
    public DataValidator dataValidator(Loader loader) {
        return new DataValidator(loader);
    }

    @Bean
    public SchemaService schemaService(Loader loader) {
        return new SchemaService(loader);
    }

    @Bean
    public QueryService queryService(Loader loader) {
        return new QueryService(loader);
    }

    @Bean
    public InstanceService instanceService(InstanceStorage instanceStorage, Loader loader, DataValidator validator, QueryService queryService) {
        return new InstanceService(instanceStorage, loader, validator, queryService);
    }

    @Bean
    public LinkService linkService(LinkStorage linkStorage, InstanceStorage instanceStorage, Loader loader, DataValidator validator) {
        return new LinkService(linkStorage, instanceStorage, loader, validator);
    }
}

