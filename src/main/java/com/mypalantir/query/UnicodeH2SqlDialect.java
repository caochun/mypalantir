package com.mypalantir.query;

import org.apache.calcite.sql.SqlDialect;
import org.apache.calcite.sql.dialect.H2SqlDialect;

/**
 * 支持 Unicode 字符的 H2 SQL 方言
 * 
 * 注意：在 Calcite 1.37 中，字符串字面量的处理主要在 RelNodeBuilder 中通过
 * 使用 NlsString 和正确的字符集来确保 Unicode 字符正确处理。
 * 
 * 这个类目前作为 H2SqlDialect 的简单包装，未来如果需要自定义 SQL 生成逻辑，
 * 可以在这里添加。
 */
public class UnicodeH2SqlDialect extends H2SqlDialect {
    public static final UnicodeH2SqlDialect DEFAULT = new UnicodeH2SqlDialect();

    public UnicodeH2SqlDialect() {
        // 使用 EMPTY_CONTEXT 作为基础，H2SqlDialect 会设置正确的数据库特定配置
        super(SqlDialect.EMPTY_CONTEXT
            .withDatabaseProduct(SqlDialect.DatabaseProduct.H2)
            .withIdentifierQuoteString("\""));
    }
}
