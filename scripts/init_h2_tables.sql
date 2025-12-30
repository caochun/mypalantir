-- 初始化 H2 数据库表结构
-- 创建车辆表和通行介质表，并建立一对一关系

-- 创建通行介质表（先创建，因为车辆表需要引用它）
CREATE TABLE IF NOT EXISTS media (
    media_id VARCHAR(50) PRIMARY KEY,
    media_number VARCHAR(50) NOT NULL UNIQUE COMMENT '介质编号',
    media_type VARCHAR(50) NOT NULL COMMENT '介质类型（ETC卡、OBU等）',
    issue_date DATE COMMENT '发行日期',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
);

-- 创建车辆表
CREATE TABLE IF NOT EXISTS vehicles (
    vehicle_id VARCHAR(50) PRIMARY KEY,
    plate_number VARCHAR(20) NOT NULL UNIQUE COMMENT '车牌号',
    vehicle_type VARCHAR(50) COMMENT '车辆类型',
    owner_name VARCHAR(100) COMMENT '车主姓名',
    obu_id VARCHAR(50) UNIQUE COMMENT '关联的OBU ID（一对一关系）',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    CONSTRAINT fk_vehicle_obu FOREIGN KEY (obu_id) REFERENCES media(media_id) ON DELETE SET NULL
);

-- 创建索引
CREATE INDEX IF NOT EXISTS idx_vehicles_plate_number ON vehicles(plate_number);
CREATE INDEX IF NOT EXISTS idx_vehicles_obu_id ON vehicles(obu_id);
CREATE INDEX IF NOT EXISTS idx_media_number ON media(media_number);
CREATE INDEX IF NOT EXISTS idx_media_type ON media(media_type);

-- 插入测试数据：通行介质（OBU）
INSERT INTO media (media_id, media_number, media_type, issue_date) VALUES
('OBU001', 'OBU-2024-001', 'OBU', '2024-01-15'),
('OBU002', 'OBU-2024-002', 'OBU', '2024-02-20'),
('OBU003', 'OBU-2024-003', 'OBU', '2024-03-10'),
('OBU004', 'OBU-2024-004', 'OBU', '2024-04-05'),
('OBU005', 'OBU-2024-005', 'OBU', '2024-05-12'),
('ETC001', 'ETC-2024-001', 'ETC卡', '2024-01-10'),
('ETC002', 'ETC-2024-002', 'ETC卡', '2024-02-15'),
('ETC003', 'ETC-2024-003', 'ETC卡', '2024-03-20');

-- 插入测试数据：车辆（与OBU建立一对一关系）
INSERT INTO vehicles (vehicle_id, plate_number, vehicle_type, owner_name, obu_id) VALUES
('VEH001', '苏A12345', '小型客车', '张三', 'OBU001'),
('VEH002', '苏B67890', '小型客车', '李四', 'OBU002'),
('VEH003', '苏C11111', '大型客车', '王五', 'OBU003'),
('VEH004', '苏D22222', '小型货车', '赵六', 'OBU004'),
('VEH005', '苏E33333', '小型客车', '钱七', 'OBU005'),
('VEH006', '苏F44444', '小型客车', '孙八', 'ETC001'),
('VEH007', '苏G55555', '小型客车', '周九', 'ETC002'),
('VEH008', '苏H66666', '小型客车', '吴十', 'ETC003');

-- 验证数据（注释掉，因为会在 Java 程序中执行）
-- SELECT '车辆数据' AS table_name, COUNT(*) AS count FROM vehicles
-- UNION ALL
-- SELECT '通行介质数据', COUNT(*) FROM media;

