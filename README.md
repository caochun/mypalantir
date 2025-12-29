# MyPalantir - Foundry Ontology 仿制项目

一个基于 Java (Spring Boot) 实现的数据模型管理平台，仿照 Palantir Foundry Ontology 的核心功能。

## 功能特性

- **元数据模型定义**：使用 YAML 格式定义对象类型、属性和关系类型
- **文件系统存储**：所有数据存储在文件系统中，便于版本控制
- **RESTful API**：提供完整的 API 用于模型查询和实例数据管理
- **数据验证**：完整的模型验证和数据验证机制

## 项目结构

```
mypalantir/
├── src/                    # Maven 标准目录结构
│   ├── main/
│   │   ├── java/          # Java 源代码
│   │   │   └── com/mypalantir/
│   │   │       ├── config/         # 配置管理
│   │   │       ├── meta/           # 元数据模型和解析器
│   │   │       ├── repository/     # 数据访问层（文件系统存储）
│   │   │       ├── service/        # 业务逻辑层
│   │   │       └── controller/      # REST 控制器
│   │   └── resources/     # 资源文件
│   │       ├── application.properties
│   │       └── static/     # Web UI 构建产物（生产模式，由 Maven 自动复制）
│   └── test/               # 测试代码
├── ontology/               # 元数据定义文件目录
├── web/                  # Web UI 源代码
│   └── dist/            # Web UI 构建产物（开发模式使用）
├── scripts/               # 脚本文件
├── data/                  # 实例数据目录（运行时生成）
└── pom.xml                # Maven 配置文件
```

### Web UI 静态文件服务

项目支持两种模式：

1. **开发模式**：使用外部路径 `./web/dist`
   - Web UI 构建后，Spring Boot 直接从 `web/dist` 目录提供静态文件
   - 适合开发环境，支持热重载

2. **生产模式**：使用 classpath 资源 `classpath:/static`
   - Maven 构建时自动将 `web/dist` 复制到 `target/classes/static/`
   - 打包到 JAR 文件中，适合生产部署
   - 修改 `application.properties` 中的 `web.static.path` 为 `classpath:/static`

## 技术栈

### 后端
- **Java 17**
- **Spring Boot 3.2.0**
- **Jackson** (JSON/YAML 处理)
- **SnakeYAML** (YAML 解析)
- **Maven** (构建工具)

### 前端
- **React 18** + **TypeScript**
- **Vite** (构建工具)
- **Tailwind CSS** (样式框架)
- **React Router** (路由)
- **Axios** (HTTP 客户端)
- **Heroicons** (图标库)

## 前置要求

- **Java 17+**
- **Maven 3.6+**
- **Node.js 18+** 和 **npm**（用于构建 Web UI）

## 快速开始

### 1. 克隆项目

```bash
git clone https://github.com/caochun/mypalantir.git
cd mypalantir
```

### 2. 安装依赖

**后端：**
```bash
mvn clean install
```

**Web UI：**
```bash
cd web
npm install
cd ..
```

### 3. 构建 Web UI

```bash
cd web
npm run build
cd ..
```

### 4. 配置（可选）

编辑 `src/main/resources/application.properties` 或使用环境变量：

**开发模式（推荐）：**
```properties
server.port=8080
schema.file.path=./ontology/schema.yaml
data.root.path=./data
web.static.path=./web/dist
```

**生产模式（打包到 JAR）：**
```properties
server.port=8080
schema.file.path=./ontology/schema.yaml
data.root.path=./data
web.static.path=classpath:/static
```

> **注意**：生产模式下，Web UI 构建产物会在 Maven 构建时自动复制到 `target/classes/static/`，并打包到 JAR 文件中。

### 5. 运行服务

**方式一：使用启动脚本（推荐）**
```bash
./scripts/start.sh
```

**方式二：使用 Maven**
```bash
mvn spring-boot:run
```

**方式三：生产模式（打包到 JAR）**
```bash
# 构建 Web UI
cd web && npm run build && cd ..

# 修改配置为生产模式（可选，默认使用开发模式）
# 编辑 src/main/resources/application.properties
# 设置 web.static.path=classpath:/static

# 构建并运行
mvn clean package
java -jar target/mypalantir-server-1.0.0.jar
```

服务启动后：
- **Web 界面**：http://localhost:8080
- **API 端点**：http://localhost:8080/api/v1
- **健康检查**：http://localhost:8080/health

> **注意**：Spring Boot 会自动提供 Web UI 静态文件，并支持 SPA 路由回退（所有非 API 请求返回 `index.html`）。

### 6. 创建测试数据（可选）

项目提供了测试数据创建脚本，可以快速创建示例数据：

**使用 Python 脚本：**
```bash
python3 scripts/create_test_data.py
```

**使用 Bash 脚本：**
```bash
bash scripts/create_test_data.sh
```

这些脚本会创建完整的测试数据，包括：
- 路段业主、收费公路、收费站等基础设施
- 车辆、通行介质等业务对象
- 交易流水、通行路径等业务数据
- 各种关系连接

## 开发模式

开发时建议前后端分离运行，便于热重载：

**终端 1 - 后端：**
```bash
mvn spring-boot:run
```

**终端 2 - Web UI：**
```bash
cd web
npm run dev
```

Web UI 开发服务器在 `http://localhost:5173`，会自动代理 API 请求到后端。

> **提示**：开发模式下，前端修改会实时热重载，后端修改需要重启 Spring Boot 应用。

## API 端点

### Schema API
- `GET /api/v1/schema/object-types` - 列出所有对象类型
- `GET /api/v1/schema/object-types/{name}` - 获取对象类型详情
- `GET /api/v1/schema/object-types/{name}/properties` - 获取对象类型属性
- `GET /api/v1/schema/object-types/{name}/outgoing-links` - 获取出边关系
- `GET /api/v1/schema/object-types/{name}/incoming-links` - 获取入边关系
- `GET /api/v1/schema/link-types` - 列出所有关系类型
- `GET /api/v1/schema/link-types/{name}` - 获取关系类型详情

### Instance API
- `POST /api/v1/instances/{objectType}` - 创建实例
- `GET /api/v1/instances/{objectType}` - 列出实例
- `GET /api/v1/instances/{objectType}/{id}` - 获取实例详情
- `PUT /api/v1/instances/{objectType}/{id}` - 更新实例
- `DELETE /api/v1/instances/{objectType}/{id}` - 删除实例

### Link API
- `POST /api/v1/links/{linkType}` - 创建关系
- `GET /api/v1/links/{linkType}` - 列出关系
- `GET /api/v1/links/{linkType}/{id}` - 获取关系详情
- `PUT /api/v1/links/{linkType}/{id}` - 更新关系
- `DELETE /api/v1/links/{linkType}/{id}` - 删除关系

### Instance Link API
- `GET /api/v1/instances/{objectType}/{id}/links/{linkType}` - 查询实例的关系
- `GET /api/v1/instances/{objectType}/{id}/connected/{linkType}` - 查询关联的实例

## 开发

### 构建

```bash
mvn clean package
```

### 运行测试

```bash
mvn test
```

### 脚本工具

项目提供了多个便捷脚本：

- **`scripts/start.sh`** - 启动服务（自动检查并构建 Web UI）
- **`scripts/create_test_data.sh`** - 创建测试数据（Bash 版本）
- **`scripts/create_test_data.py`** - 创建测试数据（Python 版本）
- **`scripts/test_api.sh`** - API 功能测试
- **`scripts/quick_test.sh`** - 快速功能验证

## 项目架构

### 目录结构说明

```
mypalantir/
├── src/main/java/com/mypalantir/
│   ├── config/          # 配置类
│   │   ├── Config.java           # 应用配置
│   │   ├── CorsConfig.java       # CORS 配置
│   │   ├── JacksonConfig.java    # Jackson JSON 配置
│   │   └── WebConfig.java        # Web MVC 配置（静态资源、SPA 路由）
│   ├── controller/      # REST 控制器
│   │   ├── SchemaController.java      # Schema 查询 API
│   │   ├── InstanceController.java    # 实例 CRUD API
│   │   ├── LinkController.java       # 关系 CRUD API
│   │   └── InstanceLinkController.java # 实例关系查询 API
│   ├── meta/            # 元数据模型
│   │   ├── OntologySchema.java   # Schema 根对象
│   │   ├── ObjectType.java       # 对象类型
│   │   ├── LinkType.java        # 关系类型
│   │   ├── Property.java        # 属性定义
│   │   ├── Parser.java          # YAML 解析器
│   │   ├── Validator.java       # Schema 验证器
│   │   └── Loader.java          # Schema 加载器
│   ├── repository/      # 数据访问层
│   │   ├── PathManager.java     # 路径管理
│   │   ├── InstanceStorage.java # 实例存储
│   │   └── LinkStorage.java     # 关系存储
│   ├── service/         # 业务逻辑层
│   │   ├── SchemaService.java   # Schema 服务
│   │   ├── InstanceService.java # 实例服务
│   │   ├── LinkService.java    # 关系服务
│   │   └── DataValidator.java  # 数据验证服务
│   └── MyPalantirApplication.java # Spring Boot 主类
├── ontology/            # 元数据定义
│   └── schema.yaml      # Schema 定义文件
├── web/                 # Web UI 源代码
│   ├── src/             # React 源代码
│   └── dist/            # 构建产物
├── scripts/             # 脚本文件
├── data/                # 实例数据（运行时生成）
└── pom.xml              # Maven 配置
```

### 核心组件

1. **Meta（元数据）层**：负责加载和验证 YAML Schema 定义
2. **Repository（存储）层**：文件系统存储实现，使用 JSON 格式
3. **Service（服务）层**：业务逻辑，包括数据验证
4. **Controller（控制器）层**：RESTful API 端点

## 数据模型

项目使用 YAML 格式定义数据模型（Schema），位于 `ontology/schema.yaml`。

Schema 定义包括：
- **对象类型（Object Types）**：定义业务对象及其属性
- **关系类型（Link Types）**：定义对象之间的关系
- **属性（Properties）**：包含数据类型、约束、验证规则

示例 Schema 定义了省中心联网收费业务的数据模型，包括：
- 基础设施：路段业主、收费公路、收费站、ETC门架等
- 业务对象：车辆、通行介质、交易流水等
- 关系：管理、包含、持有、生成等

## 许可证

本项目为仿制项目，仅供学习和研究使用。
