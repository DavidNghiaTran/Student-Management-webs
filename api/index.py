import sys, os, shutil
# Bảo đảm thư mục gốc có trong PYTHONPATH để import module nội bộ khi deploy (Vercel/Unix)
project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
if project_root not in sys.path:
    sys.path.append(project_root)

from data.thongbao import notifications as ptit_notifications

# -*- coding: utf-8 -*-
# === Đặt hàm helper classify_gpa_10 ra ngoài ===
def classify_gpa_10(gpa):
    if gpa >= 9.0:
        return "Xuất sắc"
    elif gpa >= 8.0:
        return "Giỏi"
    elif gpa >= 6.5:
        return "Khá"
    elif gpa >= 5.0:
        return "Trung bình"
    # Kiểm tra None trước khi so sánh
    elif gpa is None or gpa < 5.0:
        return "Yếu"
    else:
        return "Yếu" # Mặc định
# ===============================================

def convert_10_to_4_scale(diem_10):
    """
    Hàm trợ giúp đề xuất: Chuyển điểm 10 sang điểm 4.
    (Dựa trên thang điểm tín chỉ thông thường)
    """
    # Kiểm tra None trước khi so sánh
    if diem_10 is None:
        return 0.0 # Hoặc giá trị mặc định khác
    if diem_10 >= 8.5:
        return 4.0  # A
    elif diem_10 >= 8.0:
        return 3.5  # B+
    elif diem_10 >= 7.0:
        return 3.0  # B
    elif diem_10 >= 6.5:
        return 2.5  # C+
    elif diem_10 >= 5.5:
        return 2.0  # C
    elif diem_10 >= 5.0:
        return 1.5  # D+
    elif diem_10 >= 4.0:
        return 1.0  # D
    else:
        return 0.0  # F

import enum
import pandas as pd
import io
from flask import send_file
from flask import Flask, render_template, request, redirect, url_for, flash, abort
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager, UserMixin, login_user, logout_user, login_required, current_user
from flask_bcrypt import Bcrypt
from datetime import datetime, date
from sqlalchemy.sql import func, case, literal_column
from sqlalchemy import select, and_, text, inspect as sa_inspect
from sqlalchemy.exc import NoSuchTableError
from functools import wraps

# --- 1. CẤU HÌNH ỨNG DỤNG ---

basedir = os.path.abspath(os.path.dirname(__file__))
template_dir = os.path.join(project_root, 'templates')
static_dir = os.path.join(project_root, 'static')

def resolve_database_uri():
    """
    Build a database URI that works locally and on Vercel.
    - Prefer DATABASE_URL when provided (for hosted DBs).
    - For SQLite on Vercel, copy qlsv.db into /tmp so it is writable.
    """
    env_db_url = os.getenv('DATABASE_URL')
    if env_db_url:
        if env_db_url.startswith('postgres://'):
            env_db_url = env_db_url.replace('postgres://', 'postgresql://', 1)
        return env_db_url

    sqlite_path = os.path.join(project_root, 'qlsv.db')
    running_on_vercel = os.getenv('VERCEL') or os.getenv('VERCEL_URL')
    if running_on_vercel:
        tmp_sqlite_path = os.path.join('/tmp', 'qlsv.db')
        if not os.path.exists(tmp_sqlite_path):
            try:
                os.makedirs(os.path.dirname(tmp_sqlite_path), exist_ok=True)
                if os.path.exists(sqlite_path):
                    shutil.copy(sqlite_path, tmp_sqlite_path)
                else:
                    open(tmp_sqlite_path, 'a').close()
            except OSError as exc:
                print(f"[Database setup] Could not prepare writable SQLite copy: {exc}")
            else:
                sqlite_path = tmp_sqlite_path
        else:
            sqlite_path = tmp_sqlite_path

    return 'sqlite:///' + sqlite_path

app = Flask(__name__, template_folder=template_dir, static_folder=static_dir)
app.config['SECRET_KEY'] = 'mot-khoa-bi-mat-rat-manh-theo-yeu-cau-bao-mat'
# Cấu hình đường dẫn CSDL tùy theo môi trường (local/VERCEL/heroku)
app.config['SQLALCHEMY_DATABASE_URI'] = resolve_database_uri()
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.config['SQLALCHEMY_ENGINE_OPTIONS'] = {"pool_pre_ping": True}
# =====================

db = SQLAlchemy(app)
bcrypt = Bcrypt(app)
login_manager = LoginManager(app)

login_manager.login_view = 'login'


def ensure_teacher_profile_columns():
    """Ensure new optional teacher columns exist for older SQLite databases."""
    try:
        inspector = sa_inspect(db.engine)
        existing_columns = {col['name'] for col in inspector.get_columns('giao_vien')}
    except NoSuchTableError:
        return

    statements = []

    def add_if_missing(column_name, ddl):
        if column_name not in existing_columns:
            statements.append(ddl)

    add_if_missing('van_phong', "ALTER TABLE giao_vien ADD COLUMN van_phong VARCHAR(120)")
    add_if_missing('avatar_url', "ALTER TABLE giao_vien ADD COLUMN avatar_url VARCHAR(255)")
    add_if_missing('khoa_bo_mon', "ALTER TABLE giao_vien ADD COLUMN khoa_bo_mon VARCHAR(120)")
    add_if_missing('hoc_vi', "ALTER TABLE giao_vien ADD COLUMN hoc_vi VARCHAR(100)")

    if not statements:
        return

    for ddl in statements:
        try:
            db.session.execute(text(ddl))
        except Exception as exc:
            db.session.rollback()
            print(f"[Schema update] Could not apply '{ddl}': {exc}")
            return

    db.session.commit()


def initialize_database():
    """Ensure tables exist on cold start (needed for serverless/Vercel)."""
    with app.app_context():
        db.create_all()
        ensure_teacher_profile_columns()


initialize_database()
login_manager.login_message = 'Vui lòng đăng nhập để truy cập trang này.'
login_manager.login_message_category = 'info'


# --- 2. ĐỊNH NGHĨA MODEL (CSDL) ---
# (Giữ nguyên các Model: VaiTroEnum, TaiKhoan, SinhVien, MonHoc, KetQua, ThongBao)
class VaiTroEnum(enum.Enum):
    SINHVIEN = 'SINHVIEN'
    GIAOVIEN = 'GIAOVIEN'

# (Tìm và thay thế 3 class này trong api/index.py)

class TaiKhoan(UserMixin, db.Model):
    __tablename__ = 'tai_khoan'
    username = db.Column(db.String(50), primary_key=True)
    password = db.Column(db.String(255), nullable=False)
    vai_tro = db.Column(db.Enum(VaiTroEnum), nullable=False)

    # LƯU Ý: Chúng ta KHÔNG định nghĩa relationship ở đây.
    # backref từ SinhVien (tên 'sinh_vien') và GiaoVien (tên 'giao_vien')
    # sẽ tự động được thêm vào đây.

    def get_id(self):
        return self.username

    def set_password(self, password):
        self.password = bcrypt.generate_password_hash(password).decode('utf-8')

    def check_password(self, password):
        return bcrypt.check_password_hash(self.password, password)


class SinhVien(db.Model):
    __tablename__ = 'sinh_vien'
    ma_sv = db.Column(db.String(50), db.ForeignKey('tai_khoan.username', ondelete='CASCADE'), primary_key=True)
    ho_ten = db.Column(db.String(100), nullable=False)
    ngay_sinh = db.Column(db.Date)
    lop = db.Column(db.String(50))
    khoa = db.Column(db.String(100))
    email = db.Column(db.String(150), unique=True, nullable=True)
    location = db.Column(db.String(200), nullable=True)

    # === KHÔI PHỤC QUAN HỆ NHƯ FILE GỐC ===
    # 'backref' sẽ tự động thêm thuộc tính 'sinh_vien' vào TaiKhoan
    tai_khoan = db.relationship('TaiKhoan', 
                                backref=db.backref('sinh_vien', uselist=False, cascade='all, delete-orphan'), 
                                foreign_keys=[ma_sv])
    # ====================================

    ket_qua_list = db.relationship('KetQua', backref='sinh_vien', lazy=True, cascade='all, delete-orphan', foreign_keys='KetQua.ma_sv')


# === MODEL MỚI: GIAO_VIEN (ĐÃ SỬA) ===
class GiaoVien(db.Model):
    __tablename__ = 'giao_vien'
    ma_gv = db.Column(db.String(50), db.ForeignKey('tai_khoan.username', ondelete='CASCADE'), primary_key=True)
    
    # 1. Thông tin cá nhân cơ bản
    ho_ten = db.Column(db.String(100), nullable=False, default='Giáo viên')
    gioi_tinh = db.Column(db.String(10), nullable=True)
    ngay_sinh = db.Column(db.Date, nullable=True)
    so_dien_thoai = db.Column(db.String(20), nullable=True)
    email = db.Column(db.String(150), unique=True, nullable=True)
    dia_chi = db.Column(db.String(255), nullable=True)
    van_phong = db.Column(db.String(120), nullable=True)
    avatar_url = db.Column(db.String(255), nullable=True)

    # 2. Thông tin chuyên môn
    khoa_bo_mon = db.Column(db.String(120), nullable=True)
    hoc_vi = db.Column(db.String(100), nullable=True)
    chuc_vu = db.Column(db.String(100), nullable=True)
    linh_vuc = db.Column(db.Text, nullable=True)
    mon_hoc_phu_trach = db.Column(db.Text, nullable=True) 
    so_nam_kinh_nghiem = db.Column(db.Integer, nullable=True)

    # === THÊM QUAN HỆ (Tương tự SinhVien) ===
    # 'backref' sẽ tự động thêm thuộc tính 'giao_vien' vào TaiKhoan
    tai_khoan = db.relationship('TaiKhoan', 
                                backref=db.backref('giao_vien', uselist=False, cascade='all, delete-orphan'), 
                                foreign_keys=[ma_gv])
    # =====================================
class MonHoc(db.Model):
    __tablename__ = 'mon_hoc'
    ma_mh = db.Column(db.String(50), primary_key=True)
    ten_mh = db.Column(db.String(100), nullable=False)
    so_tin_chi = db.Column(db.Integer, nullable=False)
    
    # === THÊM CỘT MỚI ===
    # Thêm cột học kỳ. 
    # default=1 để các môn cũ (nếu dùng migration) sẽ tự động được gán vào kỳ 1
    hoc_ky = db.Column(db.Integer, nullable=False, default=1) 
    # =====================

    ket_qua_list = db.relationship('KetQua', backref='mon_hoc', lazy=True, cascade='all, delete-orphan', foreign_keys='KetQua.ma_mh')

class KetQua(db.Model):
    __tablename__ = 'ket_qua'
    # Khóa chính tổng hợp
    ma_sv = db.Column(db.String(50), db.ForeignKey('sinh_vien.ma_sv', ondelete='CASCADE'), primary_key=True)
    ma_mh = db.Column(db.String(50), db.ForeignKey('mon_hoc.ma_mh', ondelete='CASCADE'), primary_key=True)

    # Điểm thành phần (nullable=True cho phép nhập từ từ)
    diem_chuyen_can = db.Column(db.Float, nullable=True) # 20%
    diem_giua_ky = db.Column(db.Float, nullable=True)    # 20%
    diem_cuoi_ky = db.Column(db.Float, nullable=True)     # 60%

    # Điểm tổng kết (tính toán) - nullable=True vì chỉ tính khi đủ 3 điểm TP
    diem_tong_ket = db.Column(db.Float, nullable=True) # Hệ 10
    diem_chu = db.Column(db.String(2), nullable=True)   # A, B+, B, C+, C, D+, D, F

    # Hàm tính điểm tổng kết và điểm chữ (có thể gọi khi lưu)
    def calculate_final_score(self):
        # Chỉ tính khi cả 3 điểm thành phần đều đã được nhập (không phải None)
        if self.diem_chuyen_can is not None and \
           self.diem_giua_ky is not None and \
           self.diem_cuoi_ky is not None:
            # Tính điểm hệ 10
            final_score_10 = round(
                (self.diem_chuyen_can * 0.2) +
                (self.diem_giua_ky * 0.2) +
                (self.diem_cuoi_ky * 0.6),
                2 # Làm tròn 2 chữ số thập phân
            )
            self.diem_tong_ket = final_score_10
            # Tính điểm chữ từ điểm hệ 10
            self.diem_chu = convert_10_to_letter(final_score_10)
        else:
            # Nếu chưa đủ điểm, đặt là None
            self.diem_tong_ket = None
            self.diem_chu = None

# === THÊM HÀM HELPER CHUYỂN ĐIỂM CHỮ ===
# Đặt gần các hàm helper khác ở đầu file index.py
def convert_10_to_letter(diem_10):
    """Chuyển điểm 10 sang điểm chữ."""
    if diem_10 is None:
        return None # Hoặc F tùy quy định
    if diem_10 >= 8.5: return "A"
    elif diem_10 >= 8.0: return "B+"
    elif diem_10 >= 7.0: return "B"
    elif diem_10 >= 6.5: return "C+"
    elif diem_10 >= 5.5: return "C"
    elif diem_10 >= 5.0: return "D+"
    elif diem_10 >= 4.0: return "D"
    else: return "F"
# ======================================

class ThongBao(db.Model):
    __tablename__ = 'thong_bao'
    id = db.Column(db.Integer, primary_key=True)
    tieu_de = db.Column(db.String(200), nullable=False)
    noi_dung = db.Column(db.Text, nullable=False)
    ngay_gui = db.Column(db.DateTime(timezone=True), server_default=func.now())
    ma_gv = db.Column(db.String(50), db.ForeignKey('tai_khoan.username'), nullable=False)
    lop_nhan = db.Column(db.String(50), nullable=False)

    nguoi_gui = db.relationship('TaiKhoan', backref='thong_bao_da_gui', foreign_keys=[ma_gv])

# === Bang moi: Lich hoc / giang day ===
class LichHoc(db.Model):
    __tablename__ = 'lich_hoc'
    id = db.Column(db.Integer, primary_key=True)
    tieu_de = db.Column(db.String(200), nullable=False)
    lop = db.Column(db.String(50), nullable=False)
    ma_mh = db.Column(db.String(50), db.ForeignKey('mon_hoc.ma_mh'), nullable=True)
    ma_gv = db.Column(db.String(50), db.ForeignKey('tai_khoan.username'), nullable=True)
    thu_trong_tuan = db.Column(db.String(20), nullable=True)
    ngay_hoc = db.Column(db.Date, nullable=True)
    gio_bat_dau = db.Column(db.String(20), nullable=True)
    gio_ket_thuc = db.Column(db.String(20), nullable=True)
    phong = db.Column(db.String(50), nullable=True)
    ghi_chu = db.Column(db.String(255), nullable=True)
    created_at = db.Column(db.DateTime(timezone=True), server_default=func.now())

    mon_hoc = db.relationship('MonHoc', backref='lich_hoc', lazy=True)
    giao_vien = db.relationship('TaiKhoan', backref='lich_giang_day', foreign_keys=[ma_gv])


# === Bang moi: Bai tap giao cho sinh vien ===
class BaiTap(db.Model):
    __tablename__ = 'bai_tap'
    id = db.Column(db.Integer, primary_key=True)
    tieu_de = db.Column(db.String(200), nullable=False)
    noi_dung = db.Column(db.Text, nullable=False)
    lop_nhan = db.Column(db.String(50), nullable=False)
    ma_mh = db.Column(db.String(50), db.ForeignKey('mon_hoc.ma_mh'), nullable=True)
    ma_gv = db.Column(db.String(50), db.ForeignKey('tai_khoan.username'), nullable=False)
    han_nop = db.Column(db.Date, nullable=True)
    tep_dinh_kem = db.Column(db.String(255), nullable=True)
    created_at = db.Column(db.DateTime(timezone=True), server_default=func.now())

    mon_hoc = db.relationship('MonHoc', backref='bai_tap', lazy=True)
    giao_vien = db.relationship('TaiKhoan', backref='bai_tap_da_giao', foreign_keys=[ma_gv])

# --- 3. LOGIC XÁC THỰC VÀ PHÂN QUYỀN ---
@login_manager.user_loader
def load_user(user_id):
    return TaiKhoan.query.get(user_id)


_TEACHER_SCHEMA_PATCHED = False


@app.before_request
def apply_schema_patches():
    global _TEACHER_SCHEMA_PATCHED
    if _TEACHER_SCHEMA_PATCHED:
        return
    # Đảm bảo các bảng mới (lịch học, bài tập, ...) được tạo khi khởi động
    db.create_all()
    ensure_teacher_profile_columns()
    _TEACHER_SCHEMA_PATCHED = True

def role_required(vai_tro_enum):
    def decorator(f):
        @wraps(f)
        def decorated_function(*args, **kwargs):
            if not current_user.is_authenticated:
                return redirect(url_for('login'))
            if current_user.vai_tro != vai_tro_enum:
                abort(403)
            return f(*args, **kwargs)
        return decorated_function
    return decorator

@app.errorhandler(403)
def forbidden_page(e):
    return render_template('403.html'), 403

# --- 4. CÁC ROUTE (CHỨC NĂNG) ---
# (Giữ nguyên các route: home, login, logout, student_dashboard, student_profile, student_grades,
#  admin_dashboard, admin_manage_students, admin_add_student, admin_edit_student, admin_delete_student,
#  admin_manage_courses, admin_add_course, admin_edit_course, admin_delete_course,
#  admin_manage_grades, admin_enter_grades, admin_save_grades,
#  calculate_gpa_expression, calculate_gpa_4_expression, admin_reports_index)
@app.route('/')
def home():
    return redirect(url_for('login'))

# 4.1. Chức năng Chung
@app.route('/login', methods=['GET', 'POST'])
def login():
    if current_user.is_authenticated:
        if current_user.vai_tro == VaiTroEnum.SINHVIEN:
            return redirect(url_for('student_dashboard'))
        else:
            return redirect(url_for('admin_dashboard'))

    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')
        user = TaiKhoan.query.filter_by(username=username).first()

        if user and user.check_password(password):
            login_user(user)
            flash('Đăng nhập thành công!', 'success')
            if user.vai_tro == VaiTroEnum.SINHVIEN:
                return redirect(url_for('student_dashboard'))
            elif user.vai_tro == VaiTroEnum.GIAOVIEN:
                return redirect(url_for('admin_dashboard'))
        else:
            flash('Sai tên đăng nhập hoặc mật khẩu.', 'danger')

    return render_template('login.html')

@app.route('/logout')
@login_required
def logout():
    logout_user()
    flash('Bạn đã đăng xuất.', 'success')
    return redirect(url_for('login'))

# 4.2. Chức năng của Sinh viên
@app.route('/student/dashboard')
@login_required
@role_required(VaiTroEnum.SINHVIEN)
def student_dashboard():
    sinh_vien = SinhVien.query.get(current_user.username)
    ma_sv = current_user.username

    # Lấy điểm và tạo dữ liệu biểu đồ
    results = db.session.query(
        MonHoc.ma_mh,
        KetQua.diem_tong_ket,
        KetQua.diem_chu
    ).join(
        KetQua, MonHoc.ma_mh == KetQua.ma_mh
    ).filter(
        KetQua.ma_sv == ma_sv
    ).order_by(MonHoc.ma_mh).all()

    chart_points = [
        (row.ma_mh, float(row.diem_tong_ket))
        for row in results
        if row.diem_tong_ket is not None
    ]
    chart_labels = [label for label, _ in chart_points]
    chart_data = [score for _, score in chart_points]

    # Lấy thông báo
    notifications = []
    if sinh_vien and sinh_vien.lop:
        notifications = ThongBao.query.filter_by(
            lop_nhan=sinh_vien.lop
        ).order_by(
            ThongBao.ngay_gui.desc()
        ).limit(10).all()

    return render_template(
        'student_dashboard.html',
        sinh_vien=sinh_vien,
        notifications=notifications,
        chart_labels=chart_labels,
        chart_data=chart_data
    )

@app.route('/student/profile', methods=['GET', 'POST'])
@login_required
@role_required(VaiTroEnum.SINHVIEN)
def student_profile():
    sinh_vien = SinhVien.query.get_or_404(current_user.username)

    if request.method == 'POST':
        try:
            sinh_vien.ho_ten = request.form.get('ho_ten')
            sinh_vien.ngay_sinh = db.func.date(request.form.get('ngay_sinh')) if request.form.get('ngay_sinh') else None # Xử lý ngày trống
            sinh_vien.email = request.form.get('email')
            sinh_vien.location = request.form.get('location')

            db.session.commit()
            flash('Cập nhật thông tin cá nhân thành công!', 'success')
            return redirect(url_for('student_profile'))

        except Exception as e:
            db.session.rollback()
            if 'UNIQUE constraint failed: sinh_vien.email' in str(e):
                 flash('Lỗi: Email này đã được sử dụng bởi một tài khoản khác.', 'danger')
            else:
                flash(f'Lỗi khi cập nhật thông tin: {e}', 'danger')

    return render_template('student_profile.html', sv=sinh_vien)

@app.route('/student/grades')
@login_required
@role_required(VaiTroEnum.SINHVIEN)
def student_grades():
    ma_sv = current_user.username
    
    # Lấy tất cả thông tin điểm và môn học, sắp xếp theo HỌC KỲ
    results_raw = db.session.query(
        MonHoc.ma_mh,
        MonHoc.ten_mh,
        MonHoc.so_tin_chi,
        MonHoc.hoc_ky, # Lấy thông tin học kỳ
        KetQua.diem_chuyen_can,
        KetQua.diem_giua_ky,
        KetQua.diem_cuoi_ky,
        KetQua.diem_tong_ket,
        KetQua.diem_chu
    ).select_from(MonHoc).join(
        KetQua, and_(MonHoc.ma_mh == KetQua.ma_mh, KetQua.ma_sv == ma_sv), isouter=True
    ).order_by(MonHoc.hoc_ky, MonHoc.ma_mh).all() # Sắp xếp theo học kỳ

    # Khởi tạo biến cho GPA tích lũy
    total_points_10_cumulative = 0
    total_points_4_cumulative = 0
    total_credits_cumulative = 0
    
    # Cấu trúc dữ liệu mới để nhóm theo học kỳ
    semesters_data = {} # Ví dụ: { 1: { 'grades': [], 'gpa_10': 0, ... }, 2: ... }

    chart_labels = [] # Dữ liệu cho biểu đồ (vẫn dùng chung)
    chart_data = []

    for row in results_raw:
        hoc_ky = row.hoc_ky
        
        # Nếu đây là kỳ mới, tạo một entry mới trong dict
        if hoc_ky not in semesters_data:
            semesters_data[hoc_ky] = {
                'grades': [],
                'total_points_10': 0,
                'total_points_4': 0,
                'total_credits': 0,
                'gpa_10': 0.0,
                'gpa_4': 0.0
            }

        diem_tk = row.diem_tong_ket
        diem_chu = row.diem_chu

        # Chỉ tính GPA cho các môn đã có điểm tổng kết
        if diem_tk is not None:
            diem_he_4 = convert_10_to_4_scale(diem_tk)
            
            # Tính cho GPA học kỳ
            semesters_data[hoc_ky]['total_points_10'] += diem_tk * row.so_tin_chi
            semesters_data[hoc_ky]['total_points_4'] += diem_he_4 * row.so_tin_chi
            semesters_data[hoc_ky]['total_credits'] += row.so_tin_chi
            
            # Tính cho GPA tích lũy
            total_points_10_cumulative += diem_tk * row.so_tin_chi
            total_points_4_cumulative += diem_he_4 * row.so_tin_chi
            total_credits_cumulative += row.so_tin_chi

            # Dữ liệu biểu đồ (vẫn như cũ)
            chart_labels.append(f"HK{hoc_ky}-{row.ma_mh}")
            chart_data.append(diem_tk)

        # Thêm thông tin môn học vào đúng học kỳ
        semesters_data[hoc_ky]['grades'].append({
            'ma_mh': row.ma_mh,
            'ten_mh': row.ten_mh,
            'so_tin_chi': row.so_tin_chi,
            'diem_cc': row.diem_chuyen_can,
            'diem_gk': row.diem_giua_ky,
            'diem_ck': row.diem_cuoi_ky,
            'diem_tk': diem_tk,
            'diem_chu': diem_chu
        })

    # Tính toán GPA (Hệ 10 và Hệ 4) cho TỪNG học kỳ
    for ky in semesters_data:
        credits_ky = semesters_data[ky]['total_credits']
        if credits_ky > 0:
            semesters_data[ky]['gpa_10'] = semesters_data[ky]['total_points_10'] / credits_ky
            semesters_data[ky]['gpa_4'] = semesters_data[ky]['total_points_4'] / credits_ky

    # Tính GPA TÍCH LŨY (toàn bộ)
    gpa_10_cumulative = (total_points_10_cumulative / total_credits_cumulative) if total_credits_cumulative > 0 else 0.0
    gpa_4_cumulative = (total_points_4_cumulative / total_credits_cumulative) if total_credits_cumulative > 0 else 0.0

    return render_template(
        'student_grades.html',
        semesters_data=semesters_data, # Gửi cấu trúc dữ liệu mới
        gpa_10_cumulative=gpa_10_cumulative,
        gpa_4_cumulative=gpa_4_cumulative,
        chart_labels=chart_labels,
        chart_data=chart_data
    )


@app.route('/student/schedule')
@login_required
@role_required(VaiTroEnum.SINHVIEN)
def student_schedule():
    sv = SinhVien.query.get(current_user.username)
    lop_hoc = sv.lop if sv else None

    schedule_items = []
    if lop_hoc:
        schedule_items = LichHoc.query.filter_by(lop=lop_hoc).order_by(
            LichHoc.ngay_hoc.asc(),
            LichHoc.thu_trong_tuan.asc(),
            LichHoc.gio_bat_dau.asc(),
            LichHoc.id.desc()
        ).all()

    schedule_by_day = {}
    for item in schedule_items:
        key = item.ngay_hoc.strftime('%d/%m/%Y') if item.ngay_hoc else (item.thu_trong_tuan or 'Khác')
        schedule_by_day.setdefault(key, []).append(item)

    return render_template(
        'student_schedule.html',
        sv=sv,
        schedule_items=schedule_items,
        schedule_by_day=schedule_by_day
    )


@app.route('/student/assignments')
@login_required
@role_required(VaiTroEnum.SINHVIEN)
def student_assignments():
    sv = SinhVien.query.get(current_user.username)
    lop_hoc = sv.lop if sv else None

    assignments = []
    if lop_hoc:
        assignments = BaiTap.query.filter_by(lop_nhan=lop_hoc).order_by(
            case((BaiTap.han_nop == None, 1), else_=0),
            BaiTap.han_nop.asc(),
            BaiTap.created_at.desc()
        ).all()

    return render_template(
        'student_assignments.html',
        sv=sv,
        assignments=assignments,
        today=date.today()
    )


@app.route('/student/progress')
@login_required
@role_required(VaiTroEnum.SINHVIEN)
def student_progress():
    ma_sv = current_user.username
    sv = SinhVien.query.get(ma_sv)

    mon_hoc_list = MonHoc.query.order_by(MonHoc.hoc_ky, MonHoc.ma_mh).all()
    total_credits = sum(mh.so_tin_chi for mh in mon_hoc_list)
    total_courses = len(mon_hoc_list)

    ket_qua_dict = {kq.ma_mh: kq for kq in KetQua.query.filter_by(ma_sv=ma_sv).all()}

    completed_credits = 0
    completed_courses = 0
    in_progress_courses = 0
    points_10 = 0
    points_4 = 0

    progress_rows = []
    semester_summary = {}

    for mh in mon_hoc_list:
        kq = ket_qua_dict.get(mh.ma_mh)
        component_progress = 0
        if kq:
            if kq.diem_chuyen_can is not None:
                component_progress += 20
            if kq.diem_giua_ky is not None:
                component_progress += 20
            if kq.diem_cuoi_ky is not None:
                component_progress += 60

        status = 'Chưa bắt đầu'
        diem_tong_ket = None
        diem_chu = None
        if kq:
            diem_tong_ket = kq.diem_tong_ket
            diem_chu = kq.diem_chu
            if diem_tong_ket is not None:
                status = 'Hoàn thành'
                completed_courses += 1
                completed_credits += mh.so_tin_chi
                points_10 += diem_tong_ket * mh.so_tin_chi
                points_4 += convert_10_to_4_scale(diem_tong_ket) * mh.so_tin_chi
            elif component_progress > 0:
                status = 'Đang học'
                in_progress_courses += 1

        progress_rows.append({
            'ma_mh': mh.ma_mh,
            'ten_mh': mh.ten_mh,
            'hoc_ky': mh.hoc_ky,
            'so_tin_chi': mh.so_tin_chi,
            'diem_tong_ket': diem_tong_ket,
            'diem_chu': diem_chu,
            'component_progress': component_progress,
            'status': status
        })

        summary = semester_summary.setdefault(mh.hoc_ky, {'total': 0, 'completed': 0, 'in_progress': 0})
        summary['total'] += 1
        if status == 'Hoàn thành':
            summary['completed'] += 1
        elif status == 'Đang học':
            summary['in_progress'] += 1

    overall_progress_pct = (completed_credits / total_credits * 100) if total_credits > 0 else 0
    gpa_10 = (points_10 / completed_credits) if completed_credits > 0 else None
    gpa_4 = (points_4 / completed_credits) if completed_credits > 0 else None

    semester_chart_labels = []
    semester_chart_values = []
    for hk in sorted(semester_summary.keys()):
        total = semester_summary[hk]['total']
        completed = semester_summary[hk]['completed']
        pct = (completed / total * 100) if total > 0 else 0
        semester_chart_labels.append(f"HK {hk}")
        semester_chart_values.append(round(pct, 2))

    pending_courses = total_courses - completed_courses - in_progress_courses

    return render_template(
        'student_progress.html',
        sv=sv,
        progress_rows=progress_rows,
        total_credits=total_credits,
        completed_credits=completed_credits,
        completed_courses=completed_courses,
        in_progress_courses=in_progress_courses,
        pending_courses=pending_courses,
        progress_pct=overall_progress_pct,
        gpa_10=gpa_10,
        gpa_4=gpa_4,
        semester_summary=semester_summary,
        semester_chart_labels=semester_chart_labels,
        semester_chart_values=semester_chart_values
    )

# 4.3. Chức năng của Giáo viên
@app.route('/admin/dashboard')
@login_required
@role_required(VaiTroEnum.GIAOVIEN) 
def admin_dashboard():
    """Trang mặc định cho giáo viên - luôn hiển thị danh sách Thông báo chung."""
    announcements = ThongBao.query.order_by(ThongBao.ngay_gui.desc()).limit(15).all()

    notifications = []
    has_real_announcements = bool(announcements)

    if has_real_announcements:
        notifications = [
            {
                "title": tb.tieu_de,
                "date": tb.ngay_gui.strftime('%d/%m/%Y'),
                "link": None  # Có thể bổ sung link chi tiết riêng cho admin nếu cần
            }
            for tb in announcements
        ]
    else:
        for n in ptit_notifications:
            notifications.append(
                {
                    "title": n["title"],
                    "date": n["date"],
                    "link": url_for('thong_bao_chung_detail', id=n["id"])
                }
            )

    return render_template(
        'admin_dashboard.html',
        notifications=notifications,
        has_real_announcements=has_real_announcements
    )

@app.route('/admin/schedule', methods=['GET', 'POST'])
@login_required
@role_required(VaiTroEnum.GIAOVIEN)
def admin_schedule():
    danh_sach_mon_hoc = MonHoc.query.order_by(MonHoc.ten_mh).all()
    lop_hoc_tuples = db.session.query(SinhVien.lop).distinct().order_by(SinhVien.lop).all()
    danh_sach_lop = [lop[0] for lop in lop_hoc_tuples if lop[0]]

    selected_lop = request.args.get('lop')

    if request.method == 'POST':
        lop = request.form.get('lop')
        tieu_de = (request.form.get('tieu_de') or '').strip()
        ma_mh = request.form.get('ma_mh') or None
        thu_trong_tuan = (request.form.get('thu_trong_tuan') or '').strip() or None
        ngay_hoc_raw = request.form.get('ngay_hoc')
        gio_bat_dau = (request.form.get('gio_bat_dau') or '').strip() or None
        gio_ket_thuc = (request.form.get('gio_ket_thuc') or '').strip() or None
        phong = (request.form.get('phong') or '').strip() or None
        ghi_chu = (request.form.get('ghi_chu') or '').strip() or None

        if not lop:
            flash('Vui lòng chọn hoặc nhập Lớp cho lịch học.', 'danger')
            return redirect(url_for('admin_schedule', lop=selected_lop))

        if not tieu_de:
            tieu_de = f'Lịch học {lop}' if not ma_mh else f'{ma_mh} - {lop}'

        ngay_hoc = None
        if ngay_hoc_raw:
            try:
                ngay_hoc = datetime.strptime(ngay_hoc_raw, '%Y-%m-%d').date()
            except ValueError:
                flash('Ngày học không hợp lệ. Định dạng chuẩn: YYYY-MM-DD', 'danger')
                return redirect(url_for('admin_schedule', lop=lop))

        try:
            new_item = LichHoc(
                tieu_de=tieu_de,
                lop=lop,
                ma_mh=ma_mh,
                ma_gv=current_user.username,
                thu_trong_tuan=thu_trong_tuan,
                ngay_hoc=ngay_hoc,
                gio_bat_dau=gio_bat_dau,
                gio_ket_thuc=gio_ket_thuc,
                phong=phong,
                ghi_chu=ghi_chu
            )
            db.session.add(new_item)
            db.session.commit()
            flash('Đã thêm lịch học/giảng dạy.', 'success')
            return redirect(url_for('admin_schedule', lop=lop))
        except Exception as e:
            db.session.rollback()
            flash(f'Lỗi khi lưu lịch học: {e}', 'danger')
            return redirect(url_for('admin_schedule'))

    schedule_query = LichHoc.query
    if selected_lop:
        schedule_query = schedule_query.filter_by(lop=selected_lop)

    schedule_items = schedule_query.order_by(
        LichHoc.ngay_hoc.asc(),
        LichHoc.thu_trong_tuan.asc(),
        LichHoc.gio_bat_dau.asc(),
        LichHoc.id.desc()
    ).all()

    return render_template(
        'admin_schedule.html',
        danh_sach_mon_hoc=danh_sach_mon_hoc,
        danh_sach_lop=danh_sach_lop,
        schedule_items=schedule_items,
        selected_lop=selected_lop
    )


@app.route('/admin/schedule/<int:schedule_id>/delete', methods=['POST'])
@login_required
@role_required(VaiTroEnum.GIAOVIEN)
def admin_delete_schedule(schedule_id):
    schedule = LichHoc.query.get_or_404(schedule_id)
    if schedule.ma_gv and schedule.ma_gv != current_user.username:
        abort(403)
    try:
        db.session.delete(schedule)
        db.session.commit()
        flash('Đã xóa lịch học/giảng dạy.', 'success')
    except Exception as e:
        db.session.rollback()
        flash(f'Lỗi khi xóa lịch: {e}', 'danger')
    return redirect(request.referrer or url_for('admin_schedule'))


@app.route('/admin/assignments', methods=['GET', 'POST'])
@login_required
@role_required(VaiTroEnum.GIAOVIEN)
def admin_assignments():
    lop_hoc_tuples = db.session.query(SinhVien.lop).distinct().order_by(SinhVien.lop).all()
    danh_sach_lop = [lop[0] for lop in lop_hoc_tuples if lop[0]]
    danh_sach_mon_hoc = MonHoc.query.order_by(MonHoc.ten_mh).all()

    selected_lop = request.args.get('lop')
    show_all = request.args.get('all') == '1'

    if request.method == 'POST':
        tieu_de = (request.form.get('tieu_de') or '').strip()
        noi_dung = (request.form.get('noi_dung') or '').strip()
        lop_nhan = request.form.get('lop_nhan')
        ma_mh = request.form.get('ma_mh') or None
        han_nop_raw = request.form.get('han_nop')
        tep_dinh_kem = (request.form.get('tep_dinh_kem') or '').strip() or None

        if not tieu_de or not noi_dung or not lop_nhan:
            flash('Tiêu đề, nội dung và Lớp nhận là bắt buộc.', 'danger')
            return redirect(url_for('admin_assignments', lop=selected_lop))

        han_nop = None
        if han_nop_raw:
            try:
                han_nop = datetime.strptime(han_nop_raw, '%Y-%m-%d').date()
            except ValueError:
                flash('Hạn nộp không hợp lệ. Định dạng chuẩn: YYYY-MM-DD', 'danger')
                return redirect(url_for('admin_assignments', lop=lop_nhan))

        try:
            new_assignment = BaiTap(
                tieu_de=tieu_de,
                noi_dung=noi_dung,
                lop_nhan=lop_nhan,
                ma_mh=ma_mh,
                ma_gv=current_user.username,
                han_nop=han_nop,
                tep_dinh_kem=tep_dinh_kem
            )
            db.session.add(new_assignment)
            db.session.commit()
            flash('Đã giao bài tập cho sinh viên.', 'success')
            return redirect(url_for('admin_assignments', lop=lop_nhan))
        except Exception as e:
            db.session.rollback()
            flash(f'Lỗi khi tạo bài tập: {e}', 'danger')
            return redirect(url_for('admin_assignments'))

    assignments_query = BaiTap.query
    if not show_all:
        assignments_query = assignments_query.filter(BaiTap.ma_gv == current_user.username)
    if selected_lop:
        assignments_query = assignments_query.filter(BaiTap.lop_nhan == selected_lop)

    assignments = assignments_query.order_by(
        case((BaiTap.han_nop == None, 1), else_=0),
        BaiTap.han_nop.asc(),
        BaiTap.created_at.desc()
    ).all()

    return render_template(
        'admin_assignments.html',
        danh_sach_mon_hoc=danh_sach_mon_hoc,
        danh_sach_lop=danh_sach_lop,
        assignments=assignments,
        selected_lop=selected_lop,
        show_all=show_all,
        today=date.today()
    )


@app.route('/admin/assignments/<int:assignment_id>/delete', methods=['POST'])
@login_required
@role_required(VaiTroEnum.GIAOVIEN)
def admin_delete_assignment(assignment_id):
    assignment = BaiTap.query.get_or_404(assignment_id)
    if assignment.ma_gv and assignment.ma_gv != current_user.username:
        abort(403)
    try:
        db.session.delete(assignment)
        db.session.commit()
        flash('Đã xóa bài tập.', 'success')
    except Exception as e:
        db.session.rollback()
        flash(f'Lỗi khi xóa bài tập: {e}', 'danger')
    return redirect(request.referrer or url_for('admin_assignments'))


@app.route('/admin/progress')
@login_required
@role_required(VaiTroEnum.GIAOVIEN)
def admin_progress():
    lop_hoc_tuples = db.session.query(SinhVien.lop).distinct().order_by(SinhVien.lop).all()
    danh_sach_lop = [lop[0] for lop in lop_hoc_tuples if lop[0]]
    selected_lop = request.args.get('lop')

    students_query = SinhVien.query
    if selected_lop:
        students_query = students_query.filter(SinhVien.lop == selected_lop)
    students = students_query.order_by(SinhVien.lop, SinhVien.ma_sv).all()

    progress_map = {}
    for sv in students:
        progress_map[sv.ma_sv] = {
            'ma_sv': sv.ma_sv,
            'ho_ten': sv.ho_ten,
            'lop': sv.lop,
            'completed_courses': 0,
            'in_progress': 0,
            'completed_credits': 0,
            'points_10': 0,
            'points_4': 0
        }

    total_required_credits = sum(mh.so_tin_chi for mh in MonHoc.query.all())

    grade_rows = db.session.query(
        KetQua.ma_sv,
        MonHoc.so_tin_chi,
        KetQua.diem_tong_ket,
        KetQua.diem_chuyen_can,
        KetQua.diem_giua_ky,
        KetQua.diem_cuoi_ky
    ).join(MonHoc, KetQua.ma_mh == MonHoc.ma_mh)

    if selected_lop:
        grade_rows = grade_rows.join(SinhVien, KetQua.ma_sv == SinhVien.ma_sv).filter(SinhVien.lop == selected_lop)

    grade_rows = grade_rows.all()

    for row in grade_rows:
        entry = progress_map.get(row.ma_sv)
        if not entry:
            continue
        if row.diem_tong_ket is not None:
            entry['completed_courses'] += 1
            entry['completed_credits'] += row.so_tin_chi
            entry['points_10'] += row.diem_tong_ket * row.so_tin_chi
            entry['points_4'] += convert_10_to_4_scale(row.diem_tong_ket) * row.so_tin_chi
        elif any([row.diem_chuyen_can, row.diem_giua_ky, row.diem_cuoi_ky]):
            entry['in_progress'] += 1

    progress_rows = []
    completion_rates = []
    gpa_values = []
    for entry in progress_map.values():
        completed_credits = entry['completed_credits']
        gpa_10 = entry['points_10'] / completed_credits if completed_credits > 0 else None
        gpa_4 = entry['points_4'] / completed_credits if completed_credits > 0 else None
        completion_pct = (completed_credits / total_required_credits * 100) if total_required_credits > 0 else 0

        progress_rows.append({
            **entry,
            'gpa_10': gpa_10,
            'gpa_4': gpa_4,
            'completion_pct': completion_pct
        })
        completion_rates.append(completion_pct)
        if gpa_10 is not None:
            gpa_values.append(gpa_10)

    progress_rows.sort(key=lambda x: (x['lop'] or '', x['ma_sv']))

    avg_completion = sum(completion_rates) / len(completion_rates) if completion_rates else 0
    avg_gpa = sum(gpa_values) / len(gpa_values) if gpa_values else None

    return render_template(
        'admin_progress.html',
        progress_rows=progress_rows,
        danh_sach_lop=danh_sach_lop,
        selected_lop=selected_lop,
        avg_completion=avg_completion,
        avg_gpa=avg_gpa
    )

@app.route('/admin/teachers')
@login_required
@role_required(VaiTroEnum.GIAOVIEN)
def admin_manage_teachers():
    teachers = GiaoVien.query.order_by(GiaoVien.ho_ten.asc()).all()
    departments = sorted({gv.khoa_bo_mon for gv in teachers if gv.khoa_bo_mon})

    my_teacher = current_user.giao_vien
    if not my_teacher:
        my_teacher = GiaoVien.query.get(current_user.username)
    if not my_teacher:
        my_teacher = GiaoVien(
            ma_gv=current_user.username,
            ho_ten=current_user.username,
            email=f"{current_user.username}@ptit.edu.vn"
        )
        db.session.add(my_teacher)
        try:
            db.session.commit()
        except Exception:
            db.session.rollback()

    return render_template(
        'admin_manage_teachers.html',
        teachers=teachers,
        teacher_departments=departments,
        teacher_count=len(teachers),
        my_teacher=my_teacher
    )

@app.route('/admin/teachers/create', methods=['POST'])
@login_required
@role_required(VaiTroEnum.GIAOVIEN)
def admin_create_teacher():
    ma_gv = (request.form.get('ma_gv') or '').strip()
    ho_ten = (request.form.get('ho_ten') or '').strip()
    email = (request.form.get('email') or '').strip() or None
    so_dien_thoai = (request.form.get('so_dien_thoai') or '').strip() or None
    khoa_bo_mon = (request.form.get('khoa_bo_mon') or '').strip() or None
    password = (request.form.get('password') or '').strip() or None

    if not ma_gv or not ho_ten:
        flash('Mã giảng viên và Họ tên là bắt buộc.', 'danger')
        return redirect(url_for('admin_manage_teachers'))

    if TaiKhoan.query.get(ma_gv):
        flash('Mã giảng viên đã tồn tại.', 'danger')
        return redirect(url_for('admin_manage_teachers'))

    default_password = password or f"{ma_gv}@123"

    new_account = TaiKhoan(username=ma_gv, vai_tro=VaiTroEnum.GIAOVIEN)
    new_account.set_password(default_password)

    new_teacher = GiaoVien(
        ma_gv=ma_gv,
        ho_ten=ho_ten,
        email=email,
        so_dien_thoai=so_dien_thoai,
        khoa_bo_mon=khoa_bo_mon
    )

    db.session.add(new_account)
    db.session.add(new_teacher)

    try:
        db.session.commit()
        flash(f'Tạo tài khoản giảng viên {ma_gv} thành công. Mật khẩu mặc định: {default_password}', 'success')
    except Exception as e:
        db.session.rollback()
        if 'UNIQUE constraint failed: giao_vien.email' in str(e):
            flash('Email này đã được sử dụng bởi một giảng viên khác.', 'danger')
        else:
            flash(f'Lỗi khi tạo tài khoản giảng viên: {e}', 'danger')

    return redirect(url_for('admin_manage_teachers'))

@app.route('/admin/teachers/update-self', methods=['POST'])
@login_required
@role_required(VaiTroEnum.GIAOVIEN)
def admin_update_teacher_self():
    gv = current_user.giao_vien
    if not gv:
        gv = GiaoVien.query.get(current_user.username)

    if not gv:
        flash('Không tìm thấy hồ sơ giảng viên của bạn.', 'danger')
        return redirect(url_for('admin_manage_teachers'))

    gv.ho_ten = request.form.get('ho_ten') or gv.ho_ten
    gv.email = request.form.get('email') or gv.email
    gv.so_dien_thoai = request.form.get('so_dien_thoai') or gv.so_dien_thoai
    gv.khoa_bo_mon = request.form.get('khoa_bo_mon') or gv.khoa_bo_mon

    try:
        db.session.commit()
        flash('Cập nhật thông tin của bạn thành công!', 'success')
    except Exception as e:
        db.session.rollback()
        if 'UNIQUE constraint failed: giao_vien.email' in str(e):
            flash('Email này đã được sử dụng bởi một giảng viên khác.', 'danger')
        else:
            flash(f'Lỗi khi cập nhật thông tin: {e}', 'danger')

    return redirect(url_for('admin_manage_teachers'))

@app.route('/admin/profile', methods=['GET', 'POST'])
@login_required
@role_required(VaiTroEnum.GIAOVIEN)
def admin_profile():
    # Lấy hồ sơ giáo viên. 
    # Dùng get() vì chúng ta đã đảm bảo nó được tạo lúc khởi động (bên dưới)
    gv = GiaoVien.query.get(current_user.username)
    
    # Nếu (vì lý do nào đó) hồ sơ chưa tồn tại, hãy tạo nó
    if not gv:
        gv = GiaoVien(ma_gv=current_user.username, 
                      ho_ten=current_user.username,
                      email=f"{current_user.username}@ptit.edu.vn")
        db.session.add(gv)
        try:
            db.session.commit()
            flash('Đã khởi tạo hồ sơ giáo viên của bạn. Vui lòng cập nhật thông tin.', 'info')
        except Exception as e:
            db.session.rollback()
            flash(f'Lỗi khi khởi tạo hồ sơ: {e}', 'danger')
            return redirect(url_for('admin_dashboard'))

    if request.method == 'POST':
        try:
            # 1. Cập nhật thông tin cá nhân
            gv.ho_ten = request.form.get('ho_ten')
            gv.gioi_tinh = request.form.get('gioi_tinh')
            gv.ngay_sinh = db.func.date(request.form.get('ngay_sinh')) if request.form.get('ngay_sinh') else None
            gv.so_dien_thoai = request.form.get('so_dien_thoai')
            gv.email = request.form.get('email')
            gv.dia_chi = request.form.get('dia_chi')
            gv.van_phong = request.form.get('van_phong')
            gv.avatar_url = request.form.get('avatar_url')
            # (Chúng ta sẽ bỏ qua phần tải lên ảnh đại diện cho đơn giản)
            
            # 2. Cập nhật thông tin chuyên môn
            gv.khoa_bo_mon = request.form.get('khoa_bo_mon')
            gv.hoc_vi = request.form.get('hoc_vi')
            gv.chuc_vu = request.form.get('chuc_vu')
            gv.linh_vuc = request.form.get('linh_vuc')
            gv.mon_hoc_phu_trach = request.form.get('mon_hoc_phu_trach')
            gv.so_nam_kinh_nghiem = int(request.form.get('so_nam_kinh_nghiem')) if request.form.get('so_nam_kinh_nghiem') else None

            db.session.commit()
            flash('Cập nhật hồ sơ thành công!', 'success')
            return redirect(url_for('admin_profile'))
            
        except Exception as e:
            db.session.rollback()
            if 'UNIQUE constraint failed: giao_vien.email' in str(e):
                 flash('Lỗi: Email này đã được sử dụng bởi một tài khoản khác.', 'danger')
            else:
                flash(f'Lỗi khi cập nhật hồ sơ: {e}', 'danger')

    return render_template('admin_profile.html', gv=gv)

@app.route('/admin/students')
@login_required
@role_required(VaiTroEnum.GIAOVIEN)
def admin_manage_students():
    search_ma_sv = request.args.get('ma_sv', '')
    search_ho_ten = request.args.get('ho_ten', '')
    filter_lop = request.args.get('lop', '')
    filter_khoa = request.args.get('khoa', '')

    query = SinhVien.query
    if search_ma_sv:
        query = query.filter(SinhVien.ma_sv.ilike(f'%{search_ma_sv}%'))
    if search_ho_ten:
        query = query.filter(SinhVien.ho_ten.ilike(f'%{search_ho_ten}%'))
    if filter_lop:
        query = query.filter(SinhVien.lop == filter_lop)
    if filter_khoa:
        query = query.filter(SinhVien.khoa == filter_khoa)

    students = query.order_by(SinhVien.ma_sv).all()

    lop_hoc_tuples = db.session.query(SinhVien.lop).distinct().order_by(SinhVien.lop).all()
    danh_sach_lop = [lop[0] for lop in lop_hoc_tuples if lop[0]]

    khoa_tuples = db.session.query(SinhVien.khoa).distinct().order_by(SinhVien.khoa).all()
    danh_sach_khoa = [khoa[0] for khoa in khoa_tuples if khoa[0]]

    return render_template(
        'admin_manage_students.html',
        students=students,
        danh_sach_lop=danh_sach_lop,
        danh_sach_khoa=danh_sach_khoa,
        search_params={
            'ma_sv': search_ma_sv,
            'ho_ten': search_ho_ten,
            'lop': filter_lop,
            'khoa': filter_khoa
        }
    )

@app.route('/admin/students/add', methods=['GET', 'POST'])
@login_required
@role_required(VaiTroEnum.GIAOVIEN)
def admin_add_student():
    if request.method == 'POST':
        ma_sv = request.form.get('ma_sv')
        ho_ten = request.form.get('ho_ten')
        ngay_sinh = request.form.get('ngay_sinh')
        lop = request.form.get('lop')
        khoa = request.form.get('khoa')

        existing_user = TaiKhoan.query.get(ma_sv)
        if existing_user:
            flash('Lỗi: Mã sinh viên đã tồn tại.', 'danger')
            return redirect(url_for('admin_add_student'))

        try:
            default_password = f"{ma_sv}@123"
            new_account = TaiKhoan(
                username=ma_sv,
                vai_tro=VaiTroEnum.SINHVIEN
            )
            new_account.set_password(default_password)

            new_student = SinhVien(
                ma_sv=ma_sv,
                ho_ten=ho_ten,
                ngay_sinh=db.func.date(ngay_sinh) if ngay_sinh else None, # Xử lý ngày trống
                lop=lop,
                khoa=khoa
            )

            db.session.add(new_account)
            db.session.add(new_student)
            db.session.commit()

            flash('Thêm sinh viên và tài khoản thành công!', 'success')
            return redirect(url_for('admin_manage_students'))

        except Exception as e:
            db.session.rollback()
            flash(f'Đã xảy ra lỗi: {e}', 'danger')
            return redirect(url_for('admin_add_student'))

    return render_template('admin_add_student.html')

@app.route('/admin/students/edit/<ma_sv>', methods=['GET', 'POST'])
@login_required
@role_required(VaiTroEnum.GIAOVIEN)
def admin_edit_student(ma_sv):
    sv = SinhVien.query.get_or_404(ma_sv)

    if request.method == 'POST':
        try:
            sv.ho_ten = request.form.get('ho_ten')
            sv.ngay_sinh = db.func.date(request.form.get('ngay_sinh')) if request.form.get('ngay_sinh') else None # Xử lý ngày trống
            sv.lop = request.form.get('lop')
            sv.khoa = request.form.get('khoa')
            # Thêm cập nhật email và location nếu có form
            sv.email = request.form.get('email')
            sv.location = request.form.get('location')


            db.session.commit()
            flash('Cập nhật thông tin sinh viên thành công!', 'success')
            return redirect(url_for('admin_manage_students'))

        except Exception as e:
            db.session.rollback()
            flash(f'Lỗi khi cập nhật: {e}', 'danger')

    # Cần tạo template admin_edit_student.html với form đầy đủ
    return render_template('admin_edit_student.html', sv=sv)


@app.route('/admin/students/delete/<ma_sv>', methods=['POST'])
@login_required
@role_required(VaiTroEnum.GIAOVIEN)
def admin_delete_student(ma_sv):
    sv = SinhVien.query.get_or_404(ma_sv)
    try:
        db.session.delete(sv) # Cascade delete sẽ xóa TaiKhoan và KetQua
        db.session.commit()
        flash('Đã xóa sinh viên và tài khoản liên quan thành công!', 'success')
    except Exception as e:
        db.session.rollback()
        flash(f'Lỗi khi xóa sinh viên: {e}', 'danger')
    return redirect(url_for('admin_manage_students'))

# 4.4. Quản lý Môn học
@app.route('/admin/courses')
@login_required
@role_required(VaiTroEnum.GIAOVIEN)
def admin_manage_courses():
    # Sắp xếp theo học kỳ, rồi mới đến mã môn
    courses = MonHoc.query.order_by(MonHoc.hoc_ky, MonHoc.ma_mh).all() 
    return render_template('admin_manage_courses.html', courses=courses)

@app.route('/admin/courses/add', methods=['GET', 'POST'])
@login_required
@role_required(VaiTroEnum.GIAOVIEN)
def admin_add_course():
    if request.method == 'POST':
        ma_mh = request.form.get('ma_mh')
        ten_mh = request.form.get('ten_mh')
        so_tin_chi = request.form.get('so_tin_chi')
        # Lấy dữ liệu học kỳ
        hoc_ky = request.form.get('hoc_ky') 

        existing = MonHoc.query.get(ma_mh)
        if existing:
            flash('Lỗi: Mã môn học đã tồn tại.', 'danger')
            return redirect(url_for('admin_add_course'))

        try:
            new_course = MonHoc(
                ma_mh=ma_mh,
                ten_mh=ten_mh,
                so_tin_chi=int(so_tin_chi),
                # Thêm học kỳ vào
                hoc_ky=int(hoc_ky) 
            )
            db.session.add(new_course)
            db.session.commit()
            flash('Thêm môn học mới thành công!', 'success')
            return redirect(url_for('admin_manage_courses'))

        except Exception as e:
            db.session.rollback()
            flash(f'Lỗi khi thêm môn học: {e}', 'danger')

    return render_template('admin_add_course.html')

@app.route('/admin/courses/edit/<ma_mh>', methods=['GET', 'POST'])
@login_required
@role_required(VaiTroEnum.GIAOVIEN)
def admin_edit_course(ma_mh):
    course = MonHoc.query.get_or_404(ma_mh)

    if request.method == 'POST':
        try:
            course.ten_mh = request.form.get('ten_mh')
            course.so_tin_chi = int(request.form.get('so_tin_chi'))
            # Cập nhật học kỳ
            course.hoc_ky = int(request.form.get('hoc_ky')) 
            
            db.session.commit()
            flash('Cập nhật môn học thành công!', 'success')
            return redirect(url_for('admin_manage_courses'))

        except Exception as e:
            db.session.rollback()
            flash(f'Lỗi khi cập nhật: {e}', 'danger')

    return render_template('admin_edit_course.html', course=course)

@app.route('/admin/courses/delete/<ma_mh>', methods=['POST'])
@login_required
@role_required(VaiTroEnum.GIAOVIEN)
def admin_delete_course(ma_mh):
    course = MonHoc.query.get_or_404(ma_mh)
    try:
        db.session.delete(course) # Cascade delete sẽ xóa KetQua
        db.session.commit()
        flash('Đã xóa môn học thành công!', 'success')
    except Exception as e:
        db.session.rollback()
        flash(f'Lỗi khi xóa môn học: {e}', 'danger')
    return redirect(url_for('admin_manage_courses'))

# 4.5. Quản lý Điểm
# === THAY THẾ HÀM admin_manage_grades CŨ BẰNG HÀM NÀY ===
@app.route('/admin/grades', methods=['GET']) # Chỉ dùng GET
@login_required
@role_required(VaiTroEnum.GIAOVIEN)
def admin_manage_grades():
    # Lấy danh sách Lớp và Môn học cho dropdown
    lop_hoc_tuples = db.session.query(SinhVien.lop).distinct().order_by(SinhVien.lop).all()
    danh_sach_lop = [lop[0] for lop in lop_hoc_tuples if lop[0]]
    danh_sach_mon_hoc = MonHoc.query.order_by(MonHoc.ten_mh).all()

    # Lấy Lớp và Môn học được chọn từ URL (nếu có)
    selected_lop = request.args.get('lop', None)
    selected_mh_id = request.args.get('ma_mh', None)

    grades_data = []
    selected_mon_hoc = None

    # Nếu Lớp và Môn học đã được chọn -> Truy vấn điểm chi tiết
    if selected_lop and selected_mh_id:
        selected_mon_hoc = MonHoc.query.get(selected_mh_id)
        if selected_mon_hoc:
            # Lấy thông tin SV và điểm của họ cho môn này
            grades_data = db.session.query(
                SinhVien.ma_sv,
                SinhVien.ho_ten,
                KetQua.diem_chuyen_can,
                KetQua.diem_giua_ky,
                KetQua.diem_cuoi_ky,
                KetQua.diem_tong_ket,
                KetQua.diem_chu
            ).select_from(SinhVien).outerjoin( # LEFT JOIN để lấy cả SV chưa có điểm
                KetQua, and_(SinhVien.ma_sv == KetQua.ma_sv, KetQua.ma_mh == selected_mh_id)
            ).filter(
                SinhVien.lop == selected_lop # Lọc theo lớp
            ).order_by(SinhVien.ma_sv).all()

    return render_template(
        'admin_manage_grades.html',
        danh_sach_lop=danh_sach_lop,
        danh_sach_mon_hoc=danh_sach_mon_hoc,
        selected_lop=selected_lop,           # Gửi lớp đã chọn
        selected_mh_id=selected_mh_id,       # Gửi mã môn đã chọn
        selected_mon_hoc=selected_mon_hoc, # Gửi thông tin môn học đã chọn
        grades_data=grades_data            # Gửi danh sách điểm chi tiết
    )
# =======================================================

@app.route('/admin/grades/enter/<lop>/<ma_mh>', methods=['GET'])
@login_required
@role_required(VaiTroEnum.GIAOVIEN)
def admin_enter_grades(lop, ma_mh):
    mon_hoc = MonHoc.query.get_or_404(ma_mh)
    sinh_vien_list = SinhVien.query.filter_by(lop=lop).order_by(SinhVien.ma_sv).all()

    if not sinh_vien_list:
        flash(f'Không tìm thấy sinh viên nào trong lớp {lop}.', 'warning')
        return redirect(url_for('admin_manage_grades'))

    # Lấy điểm thành phần hiện có
    diem_hien_co_raw = KetQua.query.filter(
        KetQua.ma_mh == ma_mh,
        KetQua.ma_sv.in_([sv.ma_sv for sv in sinh_vien_list])
    ).all()
    # Tạo dict lưu điểm của từng SV
    diem_hien_co_dict = {
        kq.ma_sv: {
            'cc': kq.diem_chuyen_can,
            'gk': kq.diem_giua_ky,
            'ck': kq.diem_cuoi_ky,
            'tk': kq.diem_tong_ket, # Để hiển thị nếu đã tính
            'chu': kq.diem_chu      # Để hiển thị nếu đã tính
        } for kq in diem_hien_co_raw
    }

    danh_sach_nhap_diem = []
    for sv in sinh_vien_list:
        scores = diem_hien_co_dict.get(sv.ma_sv, {}) # Lấy điểm, nếu chưa có thì là dict rỗng
        danh_sach_nhap_diem.append({
            'ma_sv': sv.ma_sv,
            'ho_ten': sv.ho_ten,
            'diem_cc': scores.get('cc'),
            'diem_gk': scores.get('gk'),
            'diem_ck': scores.get('ck'),
            'diem_tk': scores.get('tk'),
            'diem_chu': scores.get('chu')
        })

    return render_template(
        'admin_enter_grades.html',
        lop=lop,
        mon_hoc=mon_hoc,
        danh_sach_nhap_diem=danh_sach_nhap_diem
    )
# === THAY THẾ HÀM admin_save_grades CŨ BẰNG HÀM NÀY ===
@app.route('/admin/grades/save', methods=['POST'])
@login_required
@role_required(VaiTroEnum.GIAOVIEN)
def admin_save_grades():
    try:
        ma_mh = request.form.get('ma_mh')
        lop = request.form.get('lop') # Lấy lại để redirect
        updated_count = 0
        created_count = 0

        # Dữ liệu form sẽ có dạng: diem_cc_MaSV, diem_gk_MaSV, diem_ck_MaSV
        scores_by_sv = {} # Gom điểm của từng SV vào dict

        # 1. Gom điểm từ form vào dict
        for key, value in request.form.items():
            if key.startswith('diem_'):
                parts = key.split('_')
                if len(parts) == 3: # Phải có dạng diem_type_MaSV
                    score_type = parts[1] # cc, gk, ck
                    ma_sv = parts[2]

                    if ma_sv not in scores_by_sv:
                        scores_by_sv[ma_sv] = {'cc': None, 'gk': None, 'ck': None}

                    # === PHẦN SỬA LỖI QUAN TRỌNG ===
                    try:
                        # Chỉ xử lý nếu 'value' (giá trị nhập vào) không rỗng
                        if value.strip(): 
                            score_float = float(value) # LẤY GIÁ TRỊ TỪ 'value', KHÔNG PHẢI 'key'
                            if not (0 <= score_float <= 10):
                                raise ValueError("Điểm không hợp lệ 0-10")
                            
                            if score_type in scores_by_sv[ma_sv]:
                                 scores_by_sv[ma_sv][score_type] = score_float
                        # Nếu value rỗng, nó sẽ giữ nguyên là None (đã khởi tạo)
                        
                    except (ValueError, TypeError):
                        # Báo lỗi bằng 'value'
                        flash(f'Lỗi: Điểm "{value}" ({score_type}) của SV {ma_sv} không hợp lệ. Giá trị này sẽ bị bỏ qua.', 'warning')
                    # === KẾT THÚC SỬA LỖI ===

        # 2. Xử lý và lưu vào CSDL
        for ma_sv, scores in scores_by_sv.items():
            
            # Kiểm tra sinh viên có tồn tại không
            student_exists = SinhVien.query.get(ma_sv)
            if not student_exists:
                flash(f"Lỗi: Mã SV '{ma_sv}' không tồn tại. Bỏ qua.", 'danger')
                continue # Bỏ qua sinh viên này

            existing_grade = KetQua.query.get((ma_sv, ma_mh))

            # Bỏ qua nếu cả 3 ô đều trống (và chưa có bản ghi)
            if all(v is None for v in scores.values()) and not existing_grade:
                continue

            if existing_grade:
                # UPDATE: Cập nhật các điểm được gửi lên
                changed = False
                # Chỉ cập nhật nếu điểm mới (từ form) là một con số
                if scores['cc'] is not None and existing_grade.diem_chuyen_can != scores['cc']:
                    existing_grade.diem_chuyen_can = scores['cc']; changed = True
                if scores['gk'] is not None and existing_grade.diem_giua_ky != scores['gk']:
                    existing_grade.diem_giua_ky = scores['gk']; changed = True
                if scores['ck'] is not None and existing_grade.diem_cuoi_ky != scores['ck']:
                    existing_grade.diem_cuoi_ky = scores['ck']; changed = True

                # TÍNH LẠI ĐIỂM (THEO YÊU CẦU CỦA BẠN)
                if changed:
                    existing_grade.calculate_final_score() # Tự động tính lại TK 10 và Chữ
                    updated_count += 1
            else:
                # INSERT: Tạo bản ghi mới
                new_grade = KetQua(
                    ma_sv=ma_sv,
                    ma_mh=ma_mh,
                    diem_chuyen_can=scores['cc'],
                    diem_giua_ky=scores['gk'],
                    diem_cuoi_ky=scores['ck']
                )
                # TÍNH ĐIỂM LẦN ĐẦU (THEO YÊU CẦU CỦA BẠN)
                new_grade.calculate_final_score() # Tự động tính TK 10 và Chữ
                db.session.add(new_grade)
                created_count += 1

        if updated_count > 0 or created_count > 0:
            db.session.commit()
            flash(f'Lưu điểm thành công! (Bản ghi mới: {created_count}, Bản ghi cập nhật: {updated_count})', 'success')
        else:
            flash('Không có thay đổi nào về điểm được lưu.', 'info')

        # Quay lại đúng trang nhập điểm đó
        return redirect(url_for('admin_enter_grades', lop=lop, ma_mh=ma_mh))

    except Exception as e:
        db.session.rollback()
        flash(f'Đã xảy ra lỗi nghiêm trọng khi lưu điểm: {e}', 'danger')
        lop = request.form.get('lop')
        ma_mh = request.form.get('ma_mh')
        if lop and ma_mh:
             return redirect(url_for('admin_enter_grades', lop=lop, ma_mh=ma_mh))
        else:
             return redirect(url_for('admin_manage_grades'))
# ========================================================
# 4.6. Báo cáo & Thống kê
# === THAY THẾ HÀM calculate_gpa_expression CŨ ===
def calculate_gpa_expression():
    """Trả về biểu thức SQLAlchemy để tính GPA hệ 10 DỰA TRÊN ĐIỂM TỔNG KẾT."""
    # Chỉ tính tổng điểm và tín chỉ cho những môn ĐÃ CÓ điểm tổng kết
    total_points = func.sum(
        case(
            (KetQua.diem_tong_ket != None, KetQua.diem_tong_ket * MonHoc.so_tin_chi),
            else_=0.0 # Bỏ qua môn chưa có điểm TK
        )
    )
    total_credits = func.sum(
        case(
            (KetQua.diem_tong_ket != None, MonHoc.so_tin_chi),
            else_=0 # Không tính tín chỉ môn chưa có điểm TK
        )
    )
    # Trả về GPA, hoặc None nếu không có tín chỉ nào hợp lệ
    return case(
        (total_credits > 0, total_points / total_credits),
        else_ = None # GPA là None nếu chưa có môn nào hoàn thành
    ).label("gpa")
# =================================================
# === THAY THẾ HÀM calculate_gpa_4_expression CŨ ===
def calculate_gpa_4_expression():
    """Trả về biểu thức SQLAlchemy để tính GPA hệ 4 DỰA TRÊN ĐIỂM TỔNG KẾT."""
    # Chuyển điểm tổng kết (hệ 10) sang điểm hệ 4
    diem_he_4 = case(
        (KetQua.diem_tong_ket >= 8.5, 4.0),
        (KetQua.diem_tong_ket >= 8.0, 3.5),
        (KetQua.diem_tong_ket >= 7.0, 3.0),
        (KetQua.diem_tong_ket >= 6.5, 2.5),
        (KetQua.diem_tong_ket >= 5.5, 2.0),
        (KetQua.diem_tong_ket >= 5.0, 1.5),
        (KetQua.diem_tong_ket >= 4.0, 1.0),
        else_=0.0
    )

    # Chỉ tính tổng điểm và tín chỉ cho những môn ĐÃ CÓ điểm tổng kết
    total_points_4 = func.sum(
        case(
            (KetQua.diem_tong_ket != None, diem_he_4 * MonHoc.so_tin_chi),
            else_=0.0
        )
    )
    total_credits = func.sum(
        case(
            (KetQua.diem_tong_ket != None, MonHoc.so_tin_chi),
            else_=0
        )
    )
    # Trả về GPA 4, hoặc None nếu không có tín chỉ hợp lệ
    return case(
        (total_credits > 0, total_points_4 / total_credits),
        else_ = None
    ).label("gpa_4")
# ==================================================
@app.route('/admin/reports')
@login_required
@role_required(VaiTroEnum.GIAOVIEN)
def admin_reports_index():
    return render_template('admin_reports_index.html')

@app.route('/admin/reports/high_gpa')
@login_required
@role_required(VaiTroEnum.GIAOVIEN)
def admin_report_high_gpa():
    GPA_THRESHOLD = 8.0
    gpa_10_expression = calculate_gpa_expression()
    gpa_4_expression = calculate_gpa_4_expression()

    results = db.session.query(
        SinhVien.ma_sv, SinhVien.ho_ten, SinhVien.lop,
        gpa_10_expression, gpa_4_expression
    ).join(
        KetQua, SinhVien.ma_sv == KetQua.ma_sv
    ).join(
        MonHoc, KetQua.ma_mh == MonHoc.ma_mh
    ).group_by(
        SinhVien.ma_sv, SinhVien.ho_ten, SinhVien.lop
    ).having(
        gpa_10_expression > GPA_THRESHOLD
    ).order_by(
        gpa_10_expression.desc()
    ).all()

    # Tính toán cho biểu đồ
    category_counts = {"Yếu": 0, "Trung bình": 0, "Khá": 0, "Giỏi": 0, "Xuất sắc": 0}
    for row in results:
        # Quan trọng: Cần kiểm tra row.gpa có phải là None không
        if row.gpa is not None:
             category = classify_gpa_10(row.gpa)
             if category in category_counts:
                 category_counts[category] += 1
    chart_labels = list(category_counts.keys())
    chart_data = list(category_counts.values())

    return render_template(
        'admin_report_high_gpa.html',
        results=results,
        threshold=GPA_THRESHOLD,
        chart_labels=chart_labels,
        chart_data=chart_data
    )

@app.route('/admin/reports/missing_grade', methods=['GET'])
@login_required
@role_required(VaiTroEnum.GIAOVIEN)
def admin_report_missing_grade():
    danh_sach_mon_hoc = MonHoc.query.order_by(MonHoc.ten_mh).all()
    selected_mh_id = request.args.get('ma_mh')
    results = []
    selected_mon_hoc = None

    if selected_mh_id:
        selected_mon_hoc = MonHoc.query.get(selected_mh_id)
        subquery_sv_da_thi = select(KetQua.ma_sv).where(KetQua.ma_mh == selected_mh_id)
        results = SinhVien.query.where(
            SinhVien.ma_sv.notin_(subquery_sv_da_thi)
        ).order_by(SinhVien.lop, SinhVien.ma_sv).all()

    return render_template(
        'admin_report_missing_grade.html',
        danh_sach_mon_hoc=danh_sach_mon_hoc,
        selected_mon_hoc=selected_mon_hoc,
        results=results
    )

@app.route('/admin/reports/class_gpa', methods=['GET'])
@login_required
@role_required(VaiTroEnum.GIAOVIEN)
def admin_report_class_gpa():
    lop_hoc_tuples = db.session.query(SinhVien.lop).distinct().order_by(SinhVien.lop).all()
    danh_sach_lop = [lop[0] for lop in lop_hoc_tuples if lop[0]]
    selected_lop = request.args.get('lop')

    lop_gpa_10 = None
    lop_gpa_4 = None
    chart_labels = []
    chart_data = []

    if selected_lop:
        # Subquery GPA 10
        gpa_10_expression = calculate_gpa_expression()
        subquery_gpa_10_sv = db.session.query(
            SinhVien.ma_sv.label('sv_id'), gpa_10_expression
        ).join(KetQua, SinhVien.ma_sv == KetQua.ma_sv)\
         .join(MonHoc, KetQua.ma_mh == MonHoc.ma_mh)\
         .filter(SinhVien.lop == selected_lop)\
         .group_by(SinhVien.ma_sv).subquery()

        # Subquery GPA 4
        gpa_4_expression = calculate_gpa_4_expression()
        subquery_gpa_4_sv = db.session.query(
            SinhVien.ma_sv.label('sv_id'), gpa_4_expression
        ).join(KetQua, SinhVien.ma_sv == KetQua.ma_sv)\
         .join(MonHoc, KetQua.ma_mh == MonHoc.ma_mh)\
         .filter(SinhVien.lop == selected_lop)\
         .group_by(SinhVien.ma_sv).subquery()

        # Tính AVG GPA
        avg_gpa_10_result = db.session.query(func.avg(subquery_gpa_10_sv.c.gpa)).scalar()
        avg_gpa_4_result = db.session.query(func.avg(subquery_gpa_4_sv.c.gpa_4)).scalar()
        lop_gpa_10 = avg_gpa_10_result if avg_gpa_10_result else 0.0
        lop_gpa_4 = avg_gpa_4_result if avg_gpa_4_result else 0.0

        # Đếm phân loại
        student_gpas = db.session.query(subquery_gpa_10_sv.c.gpa).all()
        category_counts = {"Yếu": 0, "Trung bình": 0, "Khá": 0, "Giỏi": 0, "Xuất sắc": 0}
        if student_gpas:
            for gpa_tuple in student_gpas:
                # Quan trọng: Kiểm tra gpa_tuple[0] có phải là None không
                 if gpa_tuple[0] is not None:
                      category = classify_gpa_10(gpa_tuple[0])
                      if category in category_counts:
                          category_counts[category] += 1
        chart_labels = [label for label, count in category_counts.items() if count > 0]
        chart_data = [count for label, count in category_counts.items() if count > 0]

    return render_template(
        'admin_report_class_gpa.html',
        danh_sach_lop=danh_sach_lop,
        selected_lop=selected_lop,
        lop_gpa_10=lop_gpa_10,
        lop_gpa_4=lop_gpa_4,
        chart_labels=chart_labels,
        chart_data=chart_data
    )



# === THÊM BÁO CÁO 4: PHÂN BỐ ĐIỂM ===
@app.route('/admin/reports/score_distribution', methods=['GET'])
@login_required
@role_required(VaiTroEnum.GIAOVIEN)
def admin_report_score_distribution():
    # Lấy danh sách môn học cho dropdown
    danh_sach_mon_hoc = MonHoc.query.order_by(MonHoc.ten_mh).all()
    selected_mh_id = request.args.get('ma_mh') # Lấy MaMH từ URL

    selected_mon_hoc = None
    chart_labels = []
    chart_data = []

    if selected_mh_id:
        selected_mon_hoc = MonHoc.query.get(selected_mh_id)
        if selected_mon_hoc:
            # 1. Lấy tất cả điểm tổng kết (đã có) của môn này
            scores_raw = db.session.query(
                KetQua.diem_tong_ket
            ).filter(
                KetQua.ma_mh == selected_mh_id,
                KetQua.diem_tong_ket.isnot(None) # Chỉ lấy những SV đã có điểm TK
            ).all()

            # 2. Phân loại điểm
            # Dùng hàm convert_10_to_letter đã định nghĩa
            score_distribution = {
                "A": 0, "B+": 0, "B": 0, "C+": 0, "C": 0, "D+": 0, "D": 0, "F": 0
            }
            total_students = 0

            if scores_raw:
                for score_tuple in scores_raw:
                    diem_10 = score_tuple[0]
                    letter_grade = convert_10_to_letter(diem_10) # Dùng helper
                    if letter_grade in score_distribution:
                        score_distribution[letter_grade] += 1
                        total_students += 1

            # 3. Chuẩn bị dữ liệu cho biểu đồ (chỉ lấy loại có SV)
            if total_students > 0:
                # Sắp xếp theo thứ tự điểm (A -> F)
                ordered_keys = ["A", "B+", "B", "C+", "C", "D+", "D", "F"]
                for key in ordered_keys:
                    count = score_distribution[key]
                    # Chỉ thêm vào biểu đồ nếu có SV
                    if count > 0:
                        chart_labels.append(key)
                        chart_data.append(count)

    return render_template(
        'admin_report_score_distribution.html',
        danh_sach_mon_hoc=danh_sach_mon_hoc,
        selected_mon_hoc=selected_mon_hoc,
        chart_labels=chart_labels,
        chart_data=chart_data
    )
# ========================================


# 4.7. Gửi Thông báo
@app.route('/admin/notify', methods=['GET', 'POST'])
@login_required
@role_required(VaiTroEnum.GIAOVIEN)
def admin_send_notification():
    lop_hoc_tuples = db.session.query(SinhVien.lop).distinct().order_by(SinhVien.lop).all()
    danh_sach_lop = [lop[0] for lop in lop_hoc_tuples if lop[0]]

    if request.method == 'POST':
        try:
            lop_nhan = request.form.get('lop_nhan')
            tieu_de = request.form.get('tieu_de')
            noi_dung = request.form.get('noi_dung')

            if not lop_nhan or not tieu_de or not noi_dung:
                flash('Vui lòng điền đầy đủ Lớp, Tiêu đề và Nội dung.', 'danger')
                return redirect(url_for('admin_send_notification'))

            new_notification = ThongBao(
                tieu_de=tieu_de,
                noi_dung=noi_dung,
                ma_gv=current_user.username,
                lop_nhan=lop_nhan
            )
            db.session.add(new_notification)
            db.session.commit()
            flash(f'Gửi thông báo đến lớp {lop_nhan} thành công!', 'success')
            return redirect(url_for('admin_send_notification'))

        except Exception as e:
            db.session.rollback()
            flash(f'Lỗi khi gửi thông báo: {e}', 'danger')

    return render_template('admin_send_notification.html', danh_sach_lop=danh_sach_lop)

# 4.8. Nhập Excel Sinh viên
@app.route('/admin/import_students', methods=['GET', 'POST'])
@login_required
@role_required(VaiTroEnum.GIAOVIEN)
def admin_import_students():
    if request.method == 'POST':
        if 'file' not in request.files:
            flash('Không có tệp nào được chọn.', 'danger')
            return redirect(request.url)
        file = request.files['file']
        if file.filename == '':
            flash('Chưa chọn tệp.', 'danger')
            return redirect(request.url)

        if file and file.filename.endswith(('.xls', '.xlsx')):
            try:
                df = pd.read_excel(file)
                required_columns = ['ma_sinh_vien', 'ten_sinh_vien', 'password', 'role']
                if not all(col in df.columns for col in required_columns):
                    flash(f'Lỗi: File Excel phải chứa các cột: {", ".join(required_columns)}', 'danger')
                    return redirect(request.url)

                created_count = 0
                errors = []
                for index, row in df.iterrows():
                    ma_sv = str(row['ma_sinh_vien'])
                    ten_sv = str(row['ten_sinh_vien'])
                    password = str(row['password'])
                    role_str = str(row['role']).upper()

                    if role_str != 'SINHVIEN':
                        errors.append(f'Dòng {index+2}: Vai trò "{role_str}" không hợp lệ. Bỏ qua.')
                        continue
                    existing_user = TaiKhoan.query.get(ma_sv)
                    if existing_user:
                        errors.append(f'Dòng {index+2}: Mã SV "{ma_sv}" đã tồn tại. Bỏ qua.')
                        continue

                    new_account = TaiKhoan(username=ma_sv, vai_tro=VaiTroEnum.SINHVIEN)
                    new_account.set_password(password)

                    lop_val = row.get('lop', None)
                    khoa_val = row.get('khoa', None)
                    email_val = row.get('email', None)
                    location_val = row.get('location', None)
                    ngay_sinh_val = row.get('ngay_sinh', None)
                    ngay_sinh_final = None if pd.isna(ngay_sinh_val) else pd.to_datetime(ngay_sinh_val)

                    new_student = SinhVien(
                        ma_sv=ma_sv, ho_ten=ten_sv,
                        lop = None if pd.isna(lop_val) else str(lop_val),
                        khoa = None if pd.isna(khoa_val) else str(khoa_val),
                        email = None if pd.isna(email_val) else str(email_val),
                        location = None if pd.isna(location_val) else str(location_val),
                        ngay_sinh = ngay_sinh_final
                    )
                    db.session.add(new_account)
                    db.session.add(new_student)
                    created_count += 1

                db.session.commit()
                flash(f'Nhập file thành công! Đã thêm mới {created_count} sinh viên.', 'success')
                for error in errors: flash(error, 'warning')

            except Exception as e:
                db.session.rollback()
                flash(f'Đã xảy ra lỗi nghiêm trọng khi đọc file: {e}', 'danger')

            return redirect(url_for('admin_manage_students'))

    return render_template('admin_import_students.html')

# 4.9. Nhập Excel Điểm
# === THAY THẾ HÀM admin_import_grades CŨ BẰNG HÀM NÀY ===
@app.route('/admin/grades/import', methods=['GET', 'POST'])
@login_required
@role_required(VaiTroEnum.GIAOVIEN)
def admin_import_grades():
    danh_sach_mon_hoc = MonHoc.query.order_by(MonHoc.ten_mh).all()

    if request.method == 'POST':
        if 'file' not in request.files:
            flash('Không có tệp nào được chọn.', 'danger')
            return redirect(request.url)
        file = request.files['file']
        selected_mh = request.form.get('ma_mh')
        if file.filename == '' or not selected_mh:
            flash('Vui lòng chọn Môn học và tệp Excel.', 'danger')
            return redirect(request.url)

        if file and file.filename.endswith(('.xls', '.xlsx')):
            try:
                df = pd.read_excel(file)
                # Yêu cầu 4 cột: ma_sv và 3 điểm thành phần
                required_columns = ['ma_sinh_vien', 'diem_chuyen_can', 'diem_giua_ky', 'diem_cuoi_ky']
                if not all(col in df.columns for col in required_columns):
                    flash(f'Lỗi: File Excel phải chứa các cột: {", ".join(required_columns)}', 'danger')
                    return redirect(request.url)

                updated_count = 0
                created_count = 0
                errors = []
                skipped_count = 0
                for index, row in df.iterrows():
                    ma_sv = str(row['ma_sinh_vien']).strip() if pd.notna(row['ma_sinh_vien']) else None
                    if not ma_sv: skipped_count += 1; continue

                    # Lấy và validate từng điểm thành phần
                    diem_cc, diem_gk, diem_ck = None, None, None
                    valid_scores = True
                    for col_name, score_var_name in [('diem_chuyen_can', 'diem_cc'), ('diem_giua_ky', 'diem_gk'), ('diem_cuoi_ky', 'diem_ck')]:
                        score_val = row.get(col_name, None)
                        temp_score = None
                        if pd.notna(score_val): # Chỉ xử lý nếu ô không trống
                            try:
                                temp_score = float(score_val)
                                if not (0 <= temp_score <= 10):
                                    raise ValueError("Điểm không hợp lệ")
                                # Gán giá trị hợp lệ
                                if score_var_name == 'diem_cc': diem_cc = temp_score
                                elif score_var_name == 'diem_gk': diem_gk = temp_score
                                elif score_var_name == 'diem_ck': diem_ck = temp_score
                            except (ValueError, TypeError):
                                errors.append(f"Dòng {index+2}: Điểm '{col_name}' ('{score_val}') của SV '{ma_sv}' không hợp lệ. Bản ghi này có thể không được tính điểm tổng kết.")
                                valid_scores = False # Đánh dấu nếu có điểm thành phần không hợp lệ
                                # Không gán giá trị không hợp lệ
                        # else: # Giữ None nếu ô trống

                    student_exists = SinhVien.query.get(ma_sv)
                    if not student_exists:
                        errors.append(f"Dòng {index+2}: Mã SV '{ma_sv}' không tồn tại. Bỏ qua.")
                        continue

                    existing_grade = KetQua.query.get((ma_sv, selected_mh))
                    if existing_grade:
                         # Chỉ update nếu có điểm mới từ file và khác điểm cũ
                         changed = False
                         if diem_cc is not None and existing_grade.diem_chuyen_can != diem_cc:
                              existing_grade.diem_chuyen_can = diem_cc; changed=True
                         if diem_gk is not None and existing_grade.diem_giua_ky != diem_gk:
                              existing_grade.diem_giua_ky = diem_gk; changed=True
                         if diem_ck is not None and existing_grade.diem_cuoi_ky != diem_ck:
                              existing_grade.diem_cuoi_ky = diem_ck; changed=True

                         if changed:
                              existing_grade.calculate_final_score() # Tính lại điểm TK
                              updated_count += 1
                    else:
                        new_grade = KetQua(ma_sv=ma_sv, ma_mh=selected_mh,
                                           diem_chuyen_can=diem_cc,
                                           diem_giua_ky=diem_gk,
                                           diem_cuoi_ky=diem_ck)
                        new_grade.calculate_final_score() # Tính điểm TK
                        db.session.add(new_grade)
                        created_count += 1

                if updated_count > 0 or created_count > 0:
                     db.session.commit()
                     flash(f'Nhập điểm từ Excel thành công! (Thêm mới: {created_count}, Cập nhật: {updated_count}, Bỏ qua: {skipped_count})', 'success')
                else:
                     flash('Không có điểm mới hoặc thay đổi nào được nhập.', 'info')

                for error in errors: flash(error, 'warning')

            except Exception as e:
                db.session.rollback()
                flash(f'Đã xảy ra lỗi nghiêm trọng khi đọc hoặc xử lý file: {e}', 'danger')

            return redirect(url_for('admin_manage_grades'))
        else:
             flash('Lỗi: Định dạng file không được hỗ trợ. Chỉ chấp nhận .xls hoặc .xlsx', 'danger')
             return redirect(request.url)

    return render_template('admin_import_grades.html', danh_sach_mon_hoc=danh_sach_mon_hoc)

# 4.10. Xuất Excel Điểm theo Lớp
# === THAY THẾ HÀM admin_export_grades CŨ BẰNG HÀM NÀY ===
@app.route('/admin/export_grades', methods=['GET'])
@login_required
@role_required(VaiTroEnum.GIAOVIEN)
def admin_export_grades():
    """Trang hiển thị dropdown để chọn Lớp VÀ Môn học."""
    # Lấy danh sách lớp
    lop_hoc_tuples = db.session.query(SinhVien.lop).distinct().order_by(SinhVien.lop).all()
    danh_sach_lop = [lop[0] for lop in lop_hoc_tuples if lop[0]]
    # Lấy danh sách môn học
    danh_sach_mon_hoc = MonHoc.query.order_by(MonHoc.ten_mh).all()

    return render_template(
        'admin_export_grades.html',
        danh_sach_lop=danh_sach_lop,
        danh_sach_mon_hoc=danh_sach_mon_hoc # Gửi thêm danh sách môn học
    )
# ========================================================

# === THAY THẾ HÀM admin_perform_export CŨ BẰNG HÀM NÀY ===
@app.route('/admin/export/perform', methods=['POST'])
@login_required
@role_required(VaiTroEnum.GIAOVIEN)
def admin_perform_export():
    """Xử lý logic và trả về file Excel điểm DẠNG DÀI (đã lọc)."""
    try:
        # Lấy giá trị từ form
        selected_lop = request.form.get('lop')
        selected_mh_id = request.form.get('ma_mh')

        # Bắt đầu truy vấn cơ sở
        query = db.session.query(
            SinhVien.ma_sv,
            SinhVien.ho_ten,
            SinhVien.lop,
            MonHoc.ma_mh,
            MonHoc.ten_mh,
            MonHoc.so_tin_chi,
            KetQua.diem_chuyen_can,
            KetQua.diem_giua_ky,
            KetQua.diem_cuoi_ky,
            KetQua.diem_tong_ket,
            KetQua.diem_chu
        ).select_from(SinhVien).join( # Bắt đầu từ SinhVien
            KetQua, SinhVien.ma_sv == KetQua.ma_sv, isouter=True # LEFT JOIN KetQua
        ).join(
             MonHoc, KetQua.ma_mh == MonHoc.ma_mh, isouter=True # LEFT JOIN MonHoc
        )

        # Xây dựng tên file
        file_lop_name = "ALL"
        file_mh_name = "ALL"

        # 1. Áp dụng bộ lọc Lớp (nếu người dùng chọn 1 lớp cụ thể)
        if selected_lop and selected_lop != 'all':
            query = query.filter(SinhVien.lop == selected_lop)
            file_lop_name = selected_lop.replace(" ", "_")

        # 2. Áp dụng bộ lọc Môn học (nếu người dùng chọn 1 môn cụ thể)
        if selected_mh_id and selected_mh_id != 'all':
            query = query.filter(KetQua.ma_mh == selected_mh_id)
            file_mh_name = selected_mh_id.replace(" ", "_")
        
        # 3. Chỉ lấy những SV có bản ghi điểm (nếu lọc theo môn hoặc cả 2)
        #    Nếu chỉ lọc theo lớp, ta vẫn muốn lấy cả SV chưa có điểm
        if selected_mh_id and selected_mh_id != 'all':
             query = query.filter(KetQua.ma_sv != None) # Đảm bảo có kết quả

        # Sắp xếp kết quả
        query_results = query.order_by(SinhVien.lop, SinhVien.ma_sv, MonHoc.ma_mh).all()

        if not query_results:
            flash(f'Không tìm thấy dữ liệu điểm nào cho lựa chọn của bạn.', 'warning')
            return redirect(url_for('admin_export_grades'))

        # 4. Chuẩn bị dữ liệu cho DataFrame
        data_for_df = []
        for row in query_results:
             # Bỏ qua nếu là SV trong lớp nhưng chưa có điểm môn nào (chỉ xảy ra khi lọc theo lớp)
            if row.ma_mh is None: 
                continue
                
            data_for_df.append({
                'Mã SV': row.ma_sv,
                'Họ tên': row.ho_ten,
                'Lớp': row.lop,
                'Mã MH': row.ma_mh,
                'Tên Môn học': row.ten_mh,
                'Số TC': row.so_tin_chi,
                'Điểm CC': row.diem_chuyen_can,
                'Điểm GK': row.diem_giua_ky,
                'Điểm CK': row.diem_cuoi_ky,
                'Điểm TK (10)': row.diem_tong_ket,
                'Điểm Chữ': row.diem_chu
            })
        
        if not data_for_df:
            flash(f'Không có dữ liệu điểm cụ thể nào được tìm thấy (có thể sinh viên trong lớp chưa học môn nào).', 'warning')
            return redirect(url_for('admin_export_grades'))

        df = pd.DataFrame(data_for_df)

        # 5. Tạo file Excel
        output = io.BytesIO()
        with pd.ExcelWriter(output, engine='openpyxl') as writer:
            df.to_excel(writer, sheet_name=f'Diem_{file_lop_name}', index=False)
        output.seek(0)

        # 6. Trả file về cho người dùng
        download_name = f'BangDiem_Lop_{file_lop_name}_Mon_{file_mh_name}.xlsx'
        return send_file(
            output,
            mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
            as_attachment=True,
            download_name=download_name
        )

    except Exception as e:
        flash(f'Đã xảy ra lỗi khi xuất file điểm: {e}', 'danger')
        return redirect(url_for('admin_export_grades'))
# =======================================================

# 4.11. Xuất Excel Danh sách Sinh viên
@app.route('/admin/export_students_excel')
@login_required
@role_required(VaiTroEnum.GIAOVIEN)
def admin_export_students_excel():
    try:
        search_ma_sv = request.args.get('ma_sv', '')
        search_ho_ten = request.args.get('ho_ten', '')
        filter_lop = request.args.get('lop', '')
        filter_khoa = request.args.get('khoa', '')

        query = SinhVien.query
        if search_ma_sv: query = query.filter(SinhVien.ma_sv.ilike(f'%{search_ma_sv}%'))
        if search_ho_ten: query = query.filter(SinhVien.ho_ten.ilike(f'%{search_ho_ten}%'))
        if filter_lop: query = query.filter(SinhVien.lop == filter_lop)
        if filter_khoa: query = query.filter(SinhVien.khoa == filter_khoa)

        students = query.order_by(SinhVien.ma_sv).all()
        if not students:
            flash('Không có dữ liệu sinh viên nào để xuất.', 'warning')
            return redirect(url_for('admin_manage_students'))

        data_for_df = [{'Mã SV': sv.ma_sv, 'Họ tên': sv.ho_ten, 'Ngày sinh': sv.ngay_sinh,
                        'Lớp': sv.lop, 'Khoa': sv.khoa, 'Email': sv.email,
                        'Địa chỉ (Location)': sv.location} for sv in students]
        df = pd.DataFrame(data_for_df)
        if 'Ngày sinh' in df.columns:
            # Sửa lỗi: Thêm errors='coerce' để xử lý ngày không hợp lệ thành NaT
            df['Ngày sinh'] = pd.to_datetime(df['Ngày sinh'], errors='coerce').dt.strftime('%d-%m-%Y')
            # Thay NaT thành chuỗi rỗng
            df['Ngày sinh'] = df['Ngày sinh'].fillna('')


        output = io.BytesIO()
        with pd.ExcelWriter(output, engine='openpyxl') as writer:
            df.to_excel(writer, sheet_name='DanhSachSinhVien', index=False)
        output.seek(0)

        return send_file(
            output,
            mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
            as_attachment=True,
            download_name='DanhSachSinhVien_Filtered.xlsx'
        )
    except Exception as e:
        flash(f'Đã xảy ra lỗi khi xuất file: {e}', 'danger')
        return redirect(url_for('admin_manage_students'))

from data.thongbao import notifications

# ========== THÔNG BÁO CHUNG ==========
@app.route('/thong-bao-chung')
@login_required
def thong_bao_chung():
    # Hiển thị danh sách tiêu đề + ngày
    # Chỉ truyền ptit_notifications cho template danh sách
    return render_template('thongbao_list.html', notifications=ptit_notifications)

@app.route('/thong-bao-chung/<int:id>')
@login_required
def thong_bao_chung_detail(id):
    # Hiển thị bài chi tiết
    notif = next((n for n in ptit_notifications if n["id"] == id), None)
    if not notif:
        return "Không tìm thấy thông báo", 404
    return render_template('thongbao_detail.html', notification=notif)


# --- 5. KHỞI CHẠY ỨNG DỤNG ---
if __name__ == '__main__':
    with app.app_context():
        # Tạo tất cả các bảng nếu chưa tồn tại
        db.create_all()
        ensure_teacher_profile_columns()
        
        # === CẬP NHẬT LOGIC TẠO TÀI KHOẢN MẪU ===
        if not TaiKhoan.query.filter_by(username='giaovien01').first():
            print("Tạo tài khoản giáo viên mẫu...")
            # 1. Tạo tài khoản
            admin_user = TaiKhoan(
                username='giaovien01',
                vai_tro=VaiTroEnum.GIAOVIEN
            )
            admin_user.set_password('admin@123') # Mật khẩu ví dụ
            db.session.add(admin_user)
            
            # 2. Tạo hồ sơ giáo viên (MỚI)
            admin_profile = GiaoVien(
                ma_gv='giaovien01',
                ho_ten='Giáo vụ (Mặc định)',
                email='giaovien01@ptit.edu.vn', # Email mẫu
                khoa_bo_mon='Phòng Giáo vụ'
            )
            db.session.add(admin_profile)
            
            # 3. Lưu cả hai
            db.session.commit()
            print("Tạo xong. Username: giaovien01, Password: admin@123")
    # Tắt debug khi deploy thực tế
    # Bật debug=True để xem lỗi và để server tự khởi động lại khi sửa code
    app.run(host='0.0.0.0', port=5000, debug=True)
