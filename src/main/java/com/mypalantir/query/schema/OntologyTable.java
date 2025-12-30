package com.mypalantir.query.schema;

import com.mypalantir.meta.ObjectType;
import org.apache.calcite.rel.type.RelDataType;
import org.apache.calcite.rel.type.RelDataTypeFactory;
import org.apache.calcite.schema.Statistic;
import org.apache.calcite.schema.Statistics;
import org.apache.calcite.schema.Table;
import org.apache.calcite.schema.impl.AbstractTable;

/**
 * Ontology Table 的基类
 * 表示一个 ObjectType 在 Calcite 中的表
 */
public abstract class OntologyTable extends AbstractTable {
    protected final ObjectType objectType;

    public OntologyTable(ObjectType objectType) {
        this.objectType = objectType;
    }

    @Override
    public RelDataType getRowType(RelDataTypeFactory typeFactory) {
        return buildRowType(typeFactory);
    }

    /**
     * 构建表的行类型（列定义）
     */
    protected abstract RelDataType buildRowType(RelDataTypeFactory typeFactory);

    @Override
    public Statistic getStatistic() {
        return Statistics.UNKNOWN;
    }

    public ObjectType getObjectType() {
        return objectType;
    }
}

