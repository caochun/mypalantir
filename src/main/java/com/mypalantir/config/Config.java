package com.mypalantir.config;

import org.springframework.beans.factory.annotation.Value;
import org.springframework.boot.context.properties.ConfigurationProperties;
import org.springframework.context.annotation.Configuration;

@Configuration
@ConfigurationProperties
public class Config {
    private int serverPort = 8080;
    private String serverMode = "debug";

    @Value("${schema.file.path:./ontology/schema.yaml}")
    private String schemaFilePath;
    
    @Value("${ontology.model:schema}")
    private String ontologyModel;

    @Value("${data.root.path:./data}")
    private String dataRootPath;

    private String logLevel = "info";
    private String logFile = "./logs/app.log";

    @Value("${web.static.path:./web/dist}")
    private String webStaticPath;

    public int getServerPort() {
        return serverPort;
    }

    public String getServerMode() {
        return serverMode;
    }

    public String getSchemaFilePath() {
        return schemaFilePath;
    }

    public String getDataRootPath() {
        return dataRootPath;
    }

    public String getLogLevel() {
        return logLevel;
    }

    public String getLogFile() {
        return logFile;
    }

    public String getWebStaticPath() {
        return webStaticPath;
    }
    
    public String getOntologyModel() {
        return ontologyModel;
    }
}

