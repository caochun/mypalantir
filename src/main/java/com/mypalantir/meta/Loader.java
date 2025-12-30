package com.mypalantir.meta;

import java.io.IOException;
import java.util.List;
import java.util.concurrent.locks.ReadWriteLock;
import java.util.concurrent.locks.ReentrantReadWriteLock;

public class Loader {
    private final Parser parser;
    private final ReadWriteLock lock = new ReentrantReadWriteLock();
    private OntologySchema schema;

    public Loader(String filePath) {
        this.parser = new Parser(filePath);
    }

    public void load() throws IOException, Validator.ValidationException {
        lock.writeLock().lock();
        try {
            OntologySchema parsedSchema = parser.parse();
            Validator schemaValidator = new Validator(parsedSchema);
            schemaValidator.validate();
            this.schema = parsedSchema;
        } finally {
            lock.writeLock().unlock();
        }
    }

    public OntologySchema getSchema() {
        lock.readLock().lock();
        try {
            return schema;
        } finally {
            lock.readLock().unlock();
        }
    }

    public void reload() throws IOException, Validator.ValidationException {
        load();
    }

    public ObjectType getObjectType(String name) throws NotFoundException {
        OntologySchema currentSchema = getSchema();
        if (currentSchema == null || currentSchema.getObjectTypes() == null) {
            throw new NotFoundException("schema not loaded");
        }

        for (ObjectType ot : currentSchema.getObjectTypes()) {
            if (name.equals(ot.getName())) {
                return ot;
            }
        }

        throw new NotFoundException("object type '" + name + "' not found");
    }

    public List<ObjectType> listObjectTypes() {
        OntologySchema currentSchema = getSchema();
        if (currentSchema == null) {
            return List.of();
        }
        return currentSchema.getObjectTypes() != null ? List.copyOf(currentSchema.getObjectTypes()) : List.of();
    }

    public LinkType getLinkType(String name) throws NotFoundException {
        OntologySchema currentSchema = getSchema();
        if (currentSchema == null || currentSchema.getLinkTypes() == null) {
            throw new NotFoundException("schema not loaded");
        }

        for (LinkType lt : currentSchema.getLinkTypes()) {
            if (name.equals(lt.getName())) {
                return lt;
            }
        }

        throw new NotFoundException("link type '" + name + "' not found");
    }

    public List<LinkType> listLinkTypes() {
        OntologySchema currentSchema = getSchema();
        if (currentSchema == null) {
            return List.of();
        }
        return currentSchema.getLinkTypes() != null ? List.copyOf(currentSchema.getLinkTypes()) : List.of();
    }

    public List<LinkType> getOutgoingLinks(String objectTypeName) {
        OntologySchema currentSchema = getSchema();
        if (currentSchema == null || currentSchema.getLinkTypes() == null) {
            return List.of();
        }

        return currentSchema.getLinkTypes().stream()
            .filter(lt -> objectTypeName.equals(lt.getSourceType()))
            .toList();
    }

    public List<LinkType> getIncomingLinks(String objectTypeName) {
        OntologySchema currentSchema = getSchema();
        if (currentSchema == null || currentSchema.getLinkTypes() == null) {
            return List.of();
        }

        return currentSchema.getLinkTypes().stream()
            .filter(lt -> objectTypeName.equals(lt.getTargetType()))
            .toList();
    }

    public List<DataSourceConfig> listDataSources() {
        OntologySchema currentSchema = getSchema();
        if (currentSchema == null) {
            return List.of();
        }
        return currentSchema.getDataSources() != null ? List.copyOf(currentSchema.getDataSources()) : List.of();
    }

    public DataSourceConfig getDataSourceById(String id) throws NotFoundException {
        OntologySchema currentSchema = getSchema();
        if (currentSchema == null || currentSchema.getDataSources() == null) {
            throw new NotFoundException("schema not loaded");
        }

        DataSourceConfig dataSource = currentSchema.getDataSourceById(id);
        if (dataSource == null) {
            throw new NotFoundException("data source '" + id + "' not found");
        }
        return dataSource;
    }

    public static class NotFoundException extends Exception {
        public NotFoundException(String message) {
            super(message);
        }
    }
}
