-- Bảng user
CREATE TABLE user (
    UserID INTEGER PRIMARY KEY AUTOINCREMENT,
    Name TEXT NOT NULL,
    Email TEXT UNIQUE NOT NULL,
    PasswordHash TEXT NOT NULL,
    CreatedAt DATETIME DEFAULT CURRENT_TIMESTAMP
);

-- Bảng brand
CREATE TABLE brand (
    BrandID INTEGER PRIMARY KEY AUTOINCREMENT,
    Name TEXT NOT NULL
);

-- Bảng category
CREATE TABLE category (
    CategoryID INTEGER PRIMARY KEY AUTOINCREMENT,
    Name TEXT NOT NULL,
    ParentID INTEGER,
    FOREIGN KEY (ParentID) REFERENCES category(CategoryID)
);

-- Bảng product (bao gồm PC và linh kiện)
CREATE TABLE product (
    ProductID INTEGER PRIMARY KEY AUTOINCREMENT,
    Name TEXT NOT NULL,
    CategoryID INTEGER NOT NULL,
    BrandID INTEGER,
    Price REAL NOT NULL,
    IsPC INTEGER DEFAULT 0, -- 0 = không phải PC, 1 = PC nguyên bộ
    Specs TEXT, -- JSON hoặc text
    ImageURL TEXT,
    Stock INTEGER DEFAULT 0,
    CreatedAt DATETIME DEFAULT CURRENT_TIMESTAMP,
    UpdatedAt DATETIME DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (CategoryID) REFERENCES category(CategoryID),
    FOREIGN KEY (BrandID) REFERENCES brand(BrandID)
);

-- Giỏ hàng
CREATE TABLE cart (
    CartID INTEGER PRIMARY KEY AUTOINCREMENT,
    UserID INTEGER NOT NULL,
    CreatedAt DATETIME DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (UserID) REFERENCES user(UserID)
);

CREATE TABLE cartdetail (
    CartDetailID INTEGER PRIMARY KEY AUTOINCREMENT,
    CartID INTEGER NOT NULL,
    ProductID INTEGER NOT NULL,
    Quantity INTEGER NOT NULL DEFAULT 1,
    FOREIGN KEY (CartID) REFERENCES cart(CartID) ON DELETE CASCADE,
    FOREIGN KEY (ProductID) REFERENCES product(ProductID)
);

-- Đơn hàng
CREATE TABLE "order" (
    OrderID INTEGER PRIMARY KEY AUTOINCREMENT,
    UserID INTEGER NOT NULL,
    TotalPrice REAL NOT NULL,
    Status TEXT DEFAULT 'pending',
    CreatedAt DATETIME DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (UserID) REFERENCES user(UserID)
);

CREATE TABLE orderdetail (
    OrderDetailID INTEGER PRIMARY KEY AUTOINCREMENT,
    OrderID INTEGER NOT NULL,
    ProductID INTEGER NOT NULL,
    Quantity INTEGER NOT NULL DEFAULT 1,
    Price REAL NOT NULL,
    FOREIGN KEY (OrderID) REFERENCES "order"(OrderID) ON DELETE CASCADE,
    FOREIGN KEY (ProductID) REFERENCES product(ProductID)
);

-- Nhóm tùy chọn cho PC
CREATE TABLE pc_option_group (
    OptionGroupID INTEGER PRIMARY KEY AUTOINCREMENT,
    ProductID INTEGER NOT NULL, -- PC nào
    Name TEXT NOT NULL, -- ví dụ: RAM, SSD
    IsRequired INTEGER DEFAULT 0, -- 0 = không bắt buộc
    FOREIGN KEY (ProductID) REFERENCES product(ProductID) ON DELETE CASCADE
);

-- Item trong nhóm tùy chọn
CREATE TABLE pc_option_item (
    OptionItemID INTEGER PRIMARY KEY AUTOINCREMENT,
    OptionGroupID INTEGER NOT NULL,
    ProductID INTEGER NOT NULL, -- linh kiện có thể chọn
    ExtraPrice REAL DEFAULT 0,
    FOREIGN KEY (OptionGroupID) REFERENCES pc_option_group(OptionGroupID) ON DELETE CASCADE,
    FOREIGN KEY (ProductID) REFERENCES product(ProductID)
);

-- Tag và gắn tag cho sản phẩm (phục vụ gợi ý)
CREATE TABLE tag (
    TagID INTEGER PRIMARY KEY AUTOINCREMENT,
    Name TEXT NOT NULL
);

CREATE TABLE product_tag (
    ProductTagID INTEGER PRIMARY KEY AUTOINCREMENT,
    ProductID INTEGER NOT NULL,
    TagID INTEGER NOT NULL,
    FOREIGN KEY (ProductID) REFERENCES product(ProductID) ON DELETE CASCADE,
    FOREIGN KEY (TagID) REFERENCES tag(TagID) ON DELETE CASCADE
);
