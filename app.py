from flask import Flask, request, jsonify
from flask_cors import CORS
from werkzeug.security import generate_password_hash, check_password_hash
import psycopg2
import os

app = Flask(__name__)
CORS(app) # Enable CORS for all routes

# =========================================================
# DATABASE CONFIG
# =========================================================

def get_db_connection():
    # Render provides DATABASE_URL in environment variables
    url = os.environ.get("DATABASE_URL")
    if not url:
        raise Exception("DATABASE_URL environment variable not set")
    return psycopg2.connect(url)

# =========================================================
# ROUTES
# =========================================================

@app.route("/", methods=["GET"])
def home():
    return jsonify({"status": "Backend is running"}), 200

@app.route("/signup", methods=["POST"])
def signup():
    data = request.get_json()
    name = data.get("name")
    email = data.get("email")
    password = data.get("password")

    if not all([name, email, password]):
        return jsonify({"error": "All fields required"}), 400

    hashed_password = generate_password_hash(password)

    conn = get_db_connection()
    cur = conn.cursor()

    try:
        cur.execute(
            "INSERT INTO users (name, email, password) VALUES (%s, %s, %s) RETURNING id",
            (name, email, hashed_password)
        )
        conn.commit()
        return jsonify({"message": "Signup successful"}), 201
    except psycopg2.errors.UniqueViolation:
        conn.rollback()
        return jsonify({"error": "Email already exists"}), 400
    except Exception as e:
        conn.rollback()
        print(f"Error: {e}")
        return jsonify({"error": "Signup failed"}), 500
    finally:
        cur.close()
        conn.close()

@app.route("/login", methods=["POST"])
def login():
    data = request.get_json()
    email = data.get("email")
    password = data.get("password")

    if not email or not password:
        return jsonify({"error": "Email and password required"}), 400

    conn = get_db_connection()
    cur = conn.cursor()

    try:
        cur.execute("SELECT id, name, password FROM users WHERE email = %s", (email,))
        user = cur.fetchone()
        
        if user and check_password_hash(user[2], password):
            return jsonify({
                "user_id": user[0],
                "name": user[1],
                "message": "Login successful"
            }), 200
        else:
            return jsonify({"error": "Invalid email or password"}), 401
    finally:
        cur.close()
        conn.close()

@app.route("/products", methods=["GET"])
def get_products():
    category = request.args.get("category")
    conn = get_db_connection()
    cur = conn.cursor()
    try:
        if category:
            cur.execute("SELECT id, name, price, category, image_url FROM products WHERE category = %s", (category,))
        else:
            cur.execute("SELECT id, name, price, category, image_url FROM products")
        
        rows = cur.fetchall()
        products = [{
            "id": r[0], "name": r[1], "price": float(r[2]), 
            "category": r[3], "image_url": r[4]
        } for r in rows]
        return jsonify(products), 200
    finally:
        cur.close()
        conn.close()

@app.route("/add-to-cart", methods=["POST"])
def add_to_cart():
    data = request.get_json()
    user_id = data.get("user_id")
    product_id = data.get("product_id")
    quantity = data.get("quantity", 1)

    if not user_id or not product_id:
        return jsonify({"error": "user_id and product_id required"}), 400

    conn = get_db_connection()
    cur = conn.cursor()
    try:
        cur.execute("SELECT id, quantity FROM cart WHERE user_id = %s AND product_id = %s", (user_id, product_id))
        existing = cur.fetchone()

        if existing:
            cur.execute("UPDATE cart SET quantity = %s WHERE id = %s", (existing[1] + quantity, existing[0]))
        else:
            cur.execute("INSERT INTO cart (user_id, product_id, quantity) VALUES (%s, %s, %s)", (user_id, product_id, quantity))
        conn.commit()
        return jsonify({"message": "Product added to cart"}), 200
    except Exception as e:
        conn.rollback()
        print(f"Error: {e}")
        return jsonify({"error": "Error adding to cart"}), 500
    finally:
        cur.close()
        conn.close()

@app.route("/cart", methods=["GET"])
def get_cart():
    user_id = request.args.get("user_id")
    if not user_id:
        return jsonify({"error": "user_id required"}), 400

    conn = get_db_connection()
    cur = conn.cursor()
    try:
        cur.execute("""
            SELECT c.id, p.name, p.price, p.image_url, c.quantity
            FROM cart c
            JOIN products p ON c.product_id = p.id
            WHERE c.user_id = %s
        """, (user_id,))
        rows = cur.fetchall()
        return jsonify([{
            "id": r[0], "name": r[1], "price": float(r[2]), 
            "image_url": r[3], "quantity": r[4]
        } for r in rows]), 200
    finally:
        cur.close()
        conn.close()
        # =========================================================
# ADMIN ROUTES
# =========================================================

@app.route("/admin/login", methods=["POST"])
def admin_login():
    data = request.get_json()
    email = data.get("email")
    password = data.get("password")

    conn = get_db_connection()
    cur = conn.cursor()
    try:
        cur.execute("SELECT id, name, password, is_admin FROM users WHERE email = %s", (email,))
        user = cur.fetchone()
        
        if user and check_password_hash(user[2], password):
            if user[3]:  # Check if is_admin is TRUE
                return jsonify({"admin_id": user[0], "name": user[1], "token": "admin_secret_token"}), 200
            else:
                return jsonify({"error": "Access Denied: Admins only"}), 403
        return jsonify({"error": "Invalid credentials"}), 401
    finally:
        cur.close()
        conn.close()

@app.route("/admin/stats", methods=["GET"])
def admin_stats():
    conn = get_db_connection()
    cur = conn.cursor()
    try:
        # Get total revenue
        cur.execute("SELECT COALESCE(SUM(total_amount), 0) FROM orders")
        revenue = cur.fetchone()[0]
        
        # Get total orders
        cur.execute("SELECT COUNT(*) FROM orders")
        orders_count = cur.fetchone()[0]

        # Get total products
        cur.execute("SELECT COUNT(*) FROM products")
        products_count = cur.fetchone()[0]

        return jsonify({
            "revenue": revenue, 
            "orders": orders_count, 
            "products": products_count
        }), 200
    finally:
        cur.close()
        conn.close()

@app.route("/admin/product", methods=["POST", "DELETE"])
def manage_product():
    conn = get_db_connection()
    cur = conn.cursor()
    try:
        if request.method == "POST":
            data = request.get_json()
            cur.execute(
                "INSERT INTO products (name, category, price, image_url) VALUES (%s, %s, %s, %s)",
                (data['name'], data['category'], data['price'], data['image_url'])
            )
            conn.commit()
            return jsonify({"message": "Product created"}), 201
        
        if request.method == "DELETE":
            product_id = request.args.get("id")
            cur.execute("DELETE FROM products WHERE id = %s", (product_id,))
            conn.commit()
            return jsonify({"message": "Product deleted"}), 200
            
    except Exception as e:
        conn.rollback()
        return jsonify({"error": str(e)}), 500
    finally:
        cur.close()
        conn.close()

@app.route("/admin/orders", methods=["GET", "PUT"])
def manage_orders():
    conn = get_db_connection()
    cur = conn.cursor()
    try:
        if request.method == "GET":
            cur.execute("""
                SELECT o.id, u.name, o.total_amount, o.status, o.created_at 
                FROM orders o JOIN users u ON o.user_id = u.id 
                ORDER BY o.created_at DESC
            """)
            rows = cur.fetchall()
            orders = [{
                "id": r[0], "customer": r[1], "amount": float(r[2]), 
                "status": r[3], "date": r[4]
            } for r in rows]
            return jsonify(orders), 200

        if request.method == "PUT":
            data = request.get_json()
            cur.execute("UPDATE orders SET status = %s WHERE id = %s", (data['status'], data['order_id']))
            conn.commit()
            return jsonify({"message": "Order updated"}), 200
    finally:
        cur.close()
        conn.close()

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)