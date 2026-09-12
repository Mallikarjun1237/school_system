from schoolmanagement import db, app
from datetime import datetime
from flask_login import UserMixin

class Staff(db.Model, UserMixin):
    __tablename__ = "staff"
    staff_id = db.Column(db.String(10), primary_key=True)
    name = db.Column(db.String(25), nullable=True)
    email = db.Column(db.String(50), unique=True, nullable=False)
    password = db.Column(db.String(255), nullable=False)
    role = db.Column(db.Enum("PRINCIPAL", "TEACHER", name="staff_roles_constraints"), nullable=False)
    status = db.Column(db.String(20), default="Active")
    profile_pic = db.Column(db.String(100), nullable=True, default="newleaf.jpg")
    admin_remarks = db.Column(db.Text, nullable=True)
    
    def get_id(self):
        return self.staff_id
        
class Subject(db.Model):
    __tablename__ = "subjects"
    subject_id = db.Column(db.String(15), primary_key=True)
    subject_name = db.Column(db.String(20))

class Classes(db.Model):
    __tablename__ = "classes"
    class_name = db.Column(db.String(10), unique=True, nullable=False, primary_key=True)

class Teacher_Assigned(db.Model):
    __tablename__ = "teacherassigned"
    id = db.Column(db.Integer, primary_key=True)
    staff_id = db.Column(db.String(10), db.ForeignKey("staff.staff_id"), nullable=False)
    class_name = db.Column(db.String(10), db.ForeignKey("classes.class_name"), nullable=False)
    subject_id = db.Column(db.String(15), db.ForeignKey("subjects.subject_id"), nullable=False)
    __table_args__ = (db.UniqueConstraint("class_name", "subject_id", name="unique_per_class"),)

class ClassTeacher(db.Model):
    __tablename__ = "class_teacher"
    id = db.Column(db.Integer, primary_key=True)
    class_name = db.Column(db.String(10), db.ForeignKey("classes.class_name"), nullable=False, unique=True)
    staff_id = db.Column(db.String(10), db.ForeignKey("staff.staff_id"), nullable=False, unique=True)

class Principal(db.Model):
    __tablename__ = "principal"
    staff_id = db.Column(db.String(10), db.ForeignKey("staff.staff_id"), primary_key=True)

class Student(db.Model):
    __tablename__ = "student"
    admission_no = db.Column(db.String(10), unique=True, primary_key=True, nullable=False)
    roll_no = db.Column(db.Integer, nullable=True, unique=True)
    name = db.Column(db.String(50), nullable=False)
    dob = db.Column(db.Date, nullable=True)
    academic_year = db.Column(db.String(10), nullable=True)
    class_name = db.Column(db.String(10), db.ForeignKey("classes.class_name"), nullable=False)
    __table_args__ = (db.UniqueConstraint("class_name", "roll_no", "academic_year", name="unique_roll_per_class"),)

class Exams(db.Model):
    __tablename__ = "exam"
    exam_id = db.Column(db.Integer, primary_key=True)
    exam_name = db.Column(db.String(50), nullable=False)
    academic_year = db.Column(db.String(10), nullable=True)

class Marks(db.Model):
    __tablename__ = "marks"
    mark_id = db.Column(db.Integer, primary_key=True)
    admission_no = db.Column(db.String(10), db.ForeignKey("student.admission_no"), nullable=False)
    subject_id = db.Column(db.String(15), db.ForeignKey("subjects.subject_id"), nullable=False)
    exam_id = db.Column(db.Integer, db.ForeignKey("exam.exam_id"), nullable=False)    
    marks_obtained = db.Column(db.Float, nullable=False)    
    date_updated = db.Column(db.DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)
    __table_args__ = (db.UniqueConstraint("admission_no", "exam_id", "subject_id", name="unique_student_marks"),)