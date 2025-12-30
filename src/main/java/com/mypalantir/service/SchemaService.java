package com.mypalantir.service;

import com.mypalantir.meta.DataSourceConfig;
import com.mypalantir.meta.LinkType;
import com.mypalantir.meta.Loader;
import com.mypalantir.meta.ObjectType;
import com.mypalantir.meta.Property;
import org.springframework.stereotype.Service;

import java.util.List;

@Service
public class SchemaService {
    private final Loader loader;

    public SchemaService(Loader loader) {
        this.loader = loader;
    }

    public ObjectType getObjectType(String name) throws Loader.NotFoundException {
        return loader.getObjectType(name);
    }

    public List<ObjectType> listObjectTypes() {
        return loader.listObjectTypes();
    }

    public LinkType getLinkType(String name) throws Loader.NotFoundException {
        return loader.getLinkType(name);
    }

    public List<LinkType> listLinkTypes() {
        return loader.listLinkTypes();
    }

    public List<Property> getObjectTypeProperties(String objectTypeName) throws Loader.NotFoundException {
        ObjectType objectType = loader.getObjectType(objectTypeName);
        return objectType.getProperties() != null ? objectType.getProperties() : List.of();
    }

    public List<LinkType> getOutgoingLinks(String objectTypeName) {
        return loader.getOutgoingLinks(objectTypeName);
    }

    public List<LinkType> getIncomingLinks(String objectTypeName) {
        return loader.getIncomingLinks(objectTypeName);
    }

    public List<DataSourceConfig> listDataSources() {
        return loader.listDataSources();
    }

    public DataSourceConfig getDataSourceById(String id) throws Loader.NotFoundException {
        return loader.getDataSourceById(id);
    }
}

