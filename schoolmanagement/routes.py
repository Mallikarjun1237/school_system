from flask import render_template, request, redirect, url_for, flash, jsonify, send_file, session
import re
import json
from sqlalchemy import func
import os
import base64
from io import BytesIO
from PIL import Image
from flask_login import LoginManager, login_user, logout_user, login_required, current_user
from schoolmanagement.models import Staff, Teacher_Assigned, Student, Exams, Marks, Subject, Classes, Principal, ClassTeacher
from itsdangerous import URLSafeTimedSerializer, SignatureExpired, BadTimeSignature
from schoolmanagement import app, db, serializer, mail, login_manager
from flask_mail import Message
from werkzeug.security import generate_password_hash, check_password_hash
import pandas as pd
from werkzeug.utils import secure_filename
import io

UPLOAD_FOLDER = os.path.join(app.root_path, 'static', 'uploads', 'profiles')
app.config['UPLOAD_PROFILE_FOLDER'] = UPLOAD_FOLDER
app.config['MAX_CONTENT_LENGTH'] =2 * 1024 * 1024 
os.makedirs(UPLOAD_FOLDER, exist_ok=True)


@login_manager.user_loader
def load_user(staff_id):
    return Staff.query.get(staff_id)


@app.route("/")
def index():
    return redirect(url_for('login', role='TEACHER'))


@app.route("/login/<role>",methods=["GET","POST"])
def login(role):
    if role not in ['TEACHER','CLASS_TEACHER','PRINCIPAL']:
        return redirect(url_for(login, role='TEACHER'))
    if request.method=='POST':
        email=request.form.get('email')
        password=request.form.get('password')
        db_role=role if role=="PRINCIPAL" else "TEACHER"
        user=Staff.query.filter_by(email=email, role=db_role).first()
        if role=='CLASS_TEACHER' and user:
            is_class_teacher=ClassTeacher.query.filter_by(staff_id=user.staff_id).first()
            if not is_class_teacher:
                user=None
        if user and check_password_hash(user.password, password):            
            if user.status!="Active":
                flash("Your account status is currently set to inactive,", "error")
                return redirect(uri_for('login', role=role))
            login_user(user)
            
            if role=='PRINCIPAL':
                return redirect(url_for('principal_dashboard',staff_id=user.staff_id))
            elif role=='CLASS_TEACHER':
                return redirect(url_for('classteacher_dashboard',staff_id=user.staff_id))
            else:
                return redirect(url_for('teacher_dashboard',staff_id=user.staff_id))
        else:
            flash("Invalid email or password credentials", "error")
            return redirect(url_for('login', role=role))
    return render_template("login.html", title=f"Login-{role.title()}", current_role=role)


@app.route("/logout")
@login_required
def logout():
    logout_user()
    flash("You have been successfully logged out.", "success")
    return redirect(url_for('login', role='TEACHER'))


#now the principal routes

@app.route("/dashboard/principal/<staff_id>")
@login_required
def principal_dashboard(staff_id):
    if current_user.role != "PRINCIPAL":
        flash("Unothorised access attepmt", "danger")
        return redirect(url_for('login', role="PRINCIPAL"))
    total_teachers = Staff.query.filter_by(role='TEACHER', status='Active').count()
    total_classes = Classes.query.count()
    return render_template('principal_dashboard.html', teacher_count=total_teachers, class_count=total_classes)

@app.route("/user/avatar/<staff_id>")
@login_required
def get_user_avatar(staff_id):
    user = Staff.query.get_or_404(staff_id)
    if user.profile_pic:
        response = app.response_class(user.profile_pic, mimetype='image/jpeg')
        return response
    return redirect(url_for('static', filename='images/newleaf.jpg'))

@app.route("/api/user/upload-avatar", methods=['POST'])
@login_required
def upload_avatar_api():
    if 'profile_photo' not in request.files:
        return jsonify({'success': False, 'message': 'No file segment found in request payload.'}), 400        
    file = request.files['profile_photo']
    if file.filename == '':
        return jsonify({'success': False, 'message': 'No selected image file structure detected.'}), 400
    allowed_extensions = {'.png', '.jpg', '.jpeg', '.gif'}
    file_ext = os.path.splitext(file.filename)[1].lower()    
    if file_ext not in allowed_extensions:
        return jsonify({'success': False, 'message': 'Unsupported image file type configuration.'}), 400

    try:
        file.stream.seek(0)      
        file_bytes = BytesIO(file.read())
        img = Image.open(file_bytes)
        if img.mode in ('RGBA', 'LA') or (img.mode == 'P' and 'transparency' in img.info):
            img = img.convert('RGBA')
            background = Image.new("RGB", img.size, (255, 255, 255))
            background.paste(img, mask=img.split()[3])
            img = background
        else:
            img = img.convert('RGB')

        width, height = img.size
        min_dim = min(width, height)
        left = (width - min_dim) / 2
        top = (height - min_dim) / 2
        right = (width + min_dim) / 2
        bottom = (height + min_dim) / 2
        img = img.crop((left, top, right, bottom))
        img = img.resize((200, 200), Image.Resampling.LANCZOS)
        buffer = BytesIO()
        img.save(buffer, format="JPEG", quality=85, optimize=True)
        binary_data = buffer.getvalue()
        current_user.profile_pic = binary_data
        db.session.commit()
        return jsonify({'success': True, 'message': 'Profile picture synced to database successfully!'})
        
    except Exception as e:
        db.session.rollback()
        print(f"--- SERVER IMAGE EXCEPTION TRACE: {str(e)} ---")
        return jsonify({'success': False, 'message': f'Image optimization failure: {str(e)}'}), 500

@app.route("/dashboard/principal/overview/<staff_id>", methods=['GET', 'POST'])
@login_required
def principal_overview(staff_id):
    if current_user.staff_id != staff_id or current_user.role != "PRINCIPAL":
        flash("Unauthorized administrative access.", "danger")
        return redirect(url_for('login', role='TEACHER'))

    principal = Staff.query.get(staff_id)
    if not principal:
        flash("Administrative record not found.", "danger")
        return redirect(url_for('login', role='TEACHER'))

    if request.method == 'POST':
        new_name = request.form.get('display_name')
        if new_name and new_name.strip():
            principal.name = new_name.strip()

        new_password = request.form.get('new_password')
        confirm_password = request.form.get('confirm_password')     
        if new_password and new_password.strip()!='':
            password_pattern=r"^(?=.*[a-z])(?=.*[A-Z])(?=.*\d)(?=.*[@$!%*?&^#()_+\-=\[\]{};':\"\\|,.<>\/]).{8,}$"
            if not re.match(password_pattern,new_password):
                flash("Password must contain at least 8 characters including uppercase, lowercase, number and special character.","error")          
                return redirect(url_for('principal_overview', staff_id=principal.staff_id))               
            if new_password != confirm_password:
                flash("Password confirmation mismatch. Fields must match exactly.", "danger")
                return redirect(url_for('principal_overview', staff_id=principal.staff_id))
            principal.password = generate_password_hash(new_password)
        else:
            pass

        try:
            db.session.commit()
            flash("Administrative profile settings successfully updated!", "success")
        except Exception:
            db.session.rollback()
            flash("An update error occurred within the database.", "danger")
        return redirect(url_for('principal_overview', staff_id=principal.staff_id))

    return render_template('principal_overview.html')

@app.route("/dashboard/principal/analytics")
@login_required
def principal_analytics():
    if current_user.role != "PRINCIPAL":
        flash("Access Denied.", "danger")
        return redirect(url_for('login', role='TEACHER'))

    total_students = db.session.query(func.count(Student.admission_no)).scalar() or 0
    total_teachers = Staff.query.filter_by(role='TEACHER', status='Active').count()
    total_classes = Classes.query.count()

    class_distribution = db.session.query(
        Student.class_name, 
        func.count(Student.admission_no)
    ).group_by(Student.class_name).all()
    
    class_labels = [row[0] for row in class_distribution]
    class_counts = [row[1] for row in class_distribution]

    # Chart B: Academic Progress Engine (Average marks per Class)
    # Merges Marks with Students to compute averages grouped by class division names
    academic_performance = db.session.query(
        Student.class_name,
        func.avg(Marks.marks_obtained)
    ).join(Marks, Student.admission_no == Marks.admission_no)\
     .group_by(Student.class_name).all()

    perf_labels = [row[0] for row in academic_performance]
    perf_averages = [round(row[1], 2) for row in academic_performance]

    return render_template(
        'principal_analytics.html',
        total_students=total_students,
        total_teachers=total_teachers,
        total_classes=total_classes,
        class_labels=class_labels,
        class_counts=class_counts,
        perf_labels=perf_labels,
        perf_averages=perf_averages
    )


# 1. Main Route for Assigning Teachers to Classes/Subjects & Managing Class Teachers
@app.route("/dashboard/principal/allocations", methods=['GET', 'POST'])
@login_required
def principal_allocations():
    if current_user.role != "PRINCIPAL":
        flash("Unauthorized administrative access.", "danger")
        return redirect(url_for('login', role='TEACHER'))

    if request.method == 'POST':
        staff_id = request.form.get('staff_id')
        class_name = request.form.get('class_name')
        subject_id = request.form.get('subject_id')

        if not staff_id or not class_name or not subject_id:
            flash("All allocation mapping parameters must be selected.", "warning")
            return redirect(url_for('principal_allocations'))

        # Check if this exact Subject + Class assignment has already been given to ANY teacher
        existing_assignment = Teacher_Assigned.query.filter_by(
            class_name=class_name, 
            subject_id=subject_id
        ).first()

        if existing_assignment:
            assigned_teacher = Staff.query.get(existing_assignment.staff_id)
            teacher_name = assigned_teacher.name if assigned_teacher else "Another teacher"
            flash(f"Conflict: Subject '{subject_id}' inside Class '{class_name}' is already assigned to {teacher_name}.", "danger")
        else:
            try:
                # Add the clean mapping entity to the database table
                new_allocation = Teacher_Assigned(
                    staff_id=staff_id,
                    class_name=class_name,
                    subject_id=subject_id
                )
                db.session.add(new_allocation)
                db.session.commit()
                flash("Teacher successfully allocated to the class division and subject!", "success")
            except Exception as e:
                db.session.rollback()
                flash("An error occurred during allocation processing.", "danger")

        return redirect(url_for('principal_allocations'))

    # GET Request Processing & Context Assembly
    teachers = Staff.query.filter_by(role='TEACHER', status='Active').order_by(Staff.name).all()
    classes = Classes.query.all()
    subjects = Subject.query.order_by(Subject.subject_name).all()
    
    # Fetch existing data allocations for Subject Workloads
    active_allocations = db.session.query(
        Teacher_Assigned.id,
        Staff.name.label('teacher_name'),
        Teacher_Assigned.class_name,
        Subject.subject_name,
        Subject.subject_id
    ).join(Staff, Teacher_Assigned.staff_id == Staff.staff_id)\
     .join(Subject, Teacher_Assigned.subject_id == Subject.subject_id)\
     .order_by(Teacher_Assigned.class_name).all()

    class_teacher_list = ClassTeacher.query.all()
    assigned_teacher_ids = [ct.staff_id for ct in class_teacher_list]
    
    # Create a quick key-value map dictionary: { 'staff_101': 'Class-A' } 
    # This automatically matches up and auto-selects dropdown values inside your HTML template
    assignment_mapping = {ct.staff_id: ct.class_name for ct in class_teacher_list} 

    return render_template(
        'principal_allocations.html',
        teachers=teachers,
        classes=classes,      # Matches 'all_classes' loop expectations in front-end template
        subjects=subjects,
        allocations=active_allocations,
        assigned_teacher_ids=assigned_teacher_ids, # Pass to identify class custodians
        assignment_mapping=assignment_mapping      # Pass to auto-select dropdowns
    )

# 2. Drop Route to Remove a Subject Mapping
@app.route("/dashboard/principal/allocations/delete/<int:assignment_id>", methods=['POST'])
@login_required
def delete_allocation(assignment_id):
    if current_user.role != "PRINCIPAL":
        flash("Unauthorized administrative access.", "danger")
        return redirect(url_for('login', role='TEACHER'))
        
    allocation = Teacher_Assigned.query.get_or_404(assignment_id)
    try:
        db.session.delete(allocation)
        db.session.commit()
        flash("Assignment removed successfully.", "success")
    except Exception:
        db.session.rollback()
        flash("Could not drop allocation record.", "danger")
        
    return redirect(url_for('principal_allocations'))


# 2. Route for Setting Up Classes, Subjects, and Exams
@app.route("/dashboard/principal/academic-setup", methods=['GET', 'POST'])
@login_required
def principal_academic_setup():
    if current_user.role != "PRINCIPAL":
        flash("Unauthorized administrative access.", "danger")
        return redirect(url_for('login', role='TEACHER'))

    if request.method == 'POST':
        form_type = request.form.get('form_type')

        # 🏫 ACTION A: Create a New Class Room
        if form_type == 'add_class':
            class_name = request.form.get('class_name', '').strip().upper()
            if not class_name:
                flash("Class division name cannot be left blank.", "warning")
            elif Classes.query.get(class_name):
                flash(f"Class division '{class_name}' already exists in the system.", "danger")
            else:
                new_class = Classes(class_name=class_name)
                db.session.add(new_class)
                db.session.commit()
                flash(f"Class '{class_name}' successfully added!", "success")

        # 📚 ACTION B: Create a New Academic Subject
        elif form_type == 'add_subject':
            sub_id = request.form.get('subject_id', '').strip().upper()
            sub_name = request.form.get('subject_name', '').strip()
            if not sub_id or not sub_name:
                flash("Subject credentials cannot be blank.", "warning")
            elif Subject.query.get(sub_id):
                flash(f"Subject Code '{sub_id}' is already allocated.", "danger")
            else:
                new_sub = Subject(subject_id=sub_id, subject_name=sub_name)
                db.session.add(new_sub)
                db.session.commit()
                flash(f"Subject '{sub_name}' added successfully!", "success")

        # 📝 ACTION C: Schedule a New Exam Cycle
        elif form_type == 'add_exam':
            exam_name = request.form.get('exam_name', '').strip()
            acad_year = request.form.get('academic_year', '').strip()
            if not exam_name:
                flash("Exam identification label is required.", "warning")
            else:
                new_exam = Exams(exam_name=exam_name, academic_year=acad_year or '2026')
                db.session.add(new_exam)
                db.session.commit()
                flash(f"Exam term '{exam_name}' successfully registered!", "success")

        return redirect(url_for('principal_academic_setup'))

    # GET Request Processing: Pull data sets to populate directory logs
    all_classes = Classes.query.all()
    all_subjects = Subject.query.all()
    all_exams = Exams.query.order_by(Exams.exam_id.desc()).all()

    return render_template(
        'principal_academic_setup.html',
        classes=all_classes,
        subjects=all_subjects,
        exams=all_exams
    )

# 3. Route for Monitoring Teacher Performance and Remarks
@app.route("/dashboard/principal/teacher-monitoring", methods=['GET', 'POST'])
@login_required
def principal_teacher_monitoring():
    if current_user.role != "PRINCIPAL":
        flash("Unauthorized administrative access.", "danger")
        return redirect(url_for('login', role='TEACHER'))

    if request.method == 'POST':
        target_staff_id = request.form.get('target_staff_id')
        updated_remarks = request.form.get('admin_remarks', '').strip()
        updated_status = request.form.get('status', 'Active')

        teacher = Staff.query.filter_by(staff_id=target_staff_id, role='TEACHER').first()
        if teacher:
            teacher.admin_remarks = updated_remarks if updated_remarks else None
            teacher.status = updated_status
            db.session.commit()
            flash(f"Management profile records for {teacher.name} have been updated.", "success")
        else:
            flash("Teacher record target not found.", "danger")
            
        return redirect(url_for('principal_teacher_monitoring'))

    # Query all active teachers
    teachers = Staff.query.filter_by(role='TEACHER').order_by(Staff.name).all()

    # Calculate workloads by counting entries inside the Teacher_Assigned table group
    workload_data = db.session.query(
        Teacher_Assigned.staff_id,
        func.count(Teacher_Assigned.id).label('total_classes')
    ).group_by(Teacher_Assigned.staff_id).all()

    # Map the calculation into a clean Python dictionary lookup layout
    workload_map = {row.staff_id: row.total_classes for row in workload_data}

    return render_template(
        'principal_teacher_monitoring.html',
        teachers=teachers,
        workload_map=workload_map
    )


@app.route("/api/admin/assign-class-teacher", methods=['POST'])
@login_required
def assign_class_teacher():
    # Security Guard: Only the Principal can access this endpoint
    if current_user.role != "PRINCIPAL":
        return jsonify({'success': False, 'message': 'Unauthorized administrative privileges required.'}), 403

    data = request.get_json()
    staff_id = data.get('staff_id')
    class_name = data.get('class_name')

    if not staff_id or not class_name:
        return jsonify({'success': False, 'message': 'Missing staff ID or class designation.'}), 400

    try:
        # Check if this class already has a class teacher assigned
        existing_class_assignment = ClassTeacher.query.filter_by(class_name=class_name).first()
        
        # Check if this specific teacher is already a class teacher elsewhere
        existing_teacher_assignment = ClassTeacher.query.filter_by(staff_id=staff_id).first()

        if existing_class_assignment:
            # Reassign the existing class slot to the new teacher
            existing_class_assignment.staff_id = staff_id
        elif existing_teacher_assignment:
            # If the teacher is changing classes, update their assignment row
            existing_teacher_assignment.class_name = class_name
        else:
            # Create a brand new assignment row mapping record
            new_assignment = ClassTeacher(staff_id=staff_id, class_name=class_name)
            db.session.add(new_assignment)

        db.session.commit()
        return jsonify({'success': True, 'message': f'Successfully designated as Class Teacher for {class_name}!'})

    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'message': 'Database transaction error occurred.'}), 500


#now the teacher routes below

# 1. Render Dashboard Overview Page
@app.route("/dashboard/teacher/overview/<staff_id>")
@login_required
def teacher_overview(staff_id):
    if current_user.staff_id != staff_id or current_user.role != "TEACHER":
        flash("Unauthorized access.", "danger")
        return redirect(url_for('login', role='TEACHER'))
        
    # Fetch assignments to ensure sidebar accordion stays fully functional
    assignments = Teacher_Assigned.query.filter_by(staff_id=staff_id).all()
    return render_template('teacher_overview.html', assignments=assignments)


# 2. Process Profile Updates (Name, Photo, Passwords)
@app.route("/dashboard/teacher/profile/update", methods=['POST'])
@login_required
def update_teacher_profile():
    teacher = Staff.query.get(current_user.staff_id)
    if not teacher:
        flash("User record not found.", "danger")
        return redirect(url_for('login', role='TEACHER'))
    # Update Display Name
    new_name = request.form.get('display_name')
    if new_name and new_name.strip():
        teacher.name = new_name.strip()
    # Handle Password Security Update
    new_password = request.form.get('new_password')    
    confirm_password = request.form.get('confirm_password')
    if new_password and new_password.strip()!='':
        password_pattern=r"^(?=.*[a-z])(?=.*[A-Z])(?=.*\d)(?=.*[@$!%*?&^#()_+\-=\[\]{};':\"\\|,.<>\/]).{8,}$"
        if not re.match(password_pattern,new_password):
            flash("Password must contain at least 8 characters including uppercase, lowercase, number and special character.","error")          
            return redirect(url_for('principal_overview', staff_id=principal.staff_id))               
        if new_password != confirm_password:
            flash("Password confirmation mismatch. Fields must match exactly.", "danger")
            return redirect(url_for('principal_overview', staff_id=principal.staff_id))
        teacher.password = generate_password_hash(new_password)
    else:
        pass
    try:
        db.session.commit()
        flash("Your profile settings have been successfully updated!", "success")
    except Exception as e:
        db.session.rollback()
        flash("An update conflict occurred inside the database infrastructure.", "danger")

    return redirect(url_for('teacher_overview', staff_id=teacher.staff_id))



@app.route("/grades/download-template")
@login_required
def download_excel_template():
    if current_user.role != "TEACHER":
        flash("Unauthorized access.", "danger")
        return redirect(url_for('login', role='TEACHER'))
        
    # Define the exact columns the upload engine looks for
    columns = ['admission_no', 'subject_id', 'exam_id', 'marks_obtained']
    
    # Create an empty dataframe with these columns
    df = pd.DataFrame(columns=columns)
    
    # Save the Excel file directly into memory instead of writing to disk
    output = io.BytesIO()
    with pd.ExcelWriter(output, engine='openpyxl') as writer:
        df.to_excel(writer, index=False, sheet_name='GradeTemplate')
    output.seek(0)
    
    return send_file(
        output,
        mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
        as_attachment=True,
        download_name='bulk_marks_template.xlsx'
    )


@app.route("/dashboard/teacher/<staff_id>")
@login_required
def teacher_dashboard(staff_id):
    if current_user.staff_id != staff_id or current_user.role!="TEACHER":
        flash("Unothorised access attepmt", "error")
        return redirect(url_for('login', role="TEACHER"))
    assignments=Teacher_Assigned.query.filter_by(staff_id=staff_id).all()
    managed_class = ClassTeacher.query.filter_by(staff_id=current_user.staff_id).first()
    session['is_class_teacher'] = True if managed_class else False
    session['managed_class_name'] = managed_class.class_name if managed_class else None
    return render_template('teacher_dashboard.html', assignments=assignments, is_class_teacher=session.get('is_class_teacher'))


@app.route("/dashboard/teacher/class/<class_name>")
@login_required
def view_class_roster(class_name):
    if current_user.role != "TEACHER":
        flash("Access Denied.", "danger")
        return redirect(url_for('login', role='TEACHER'))
        
    # 1. Security Check: Verify this teacher is actually assigned to teach this class
    has_access = Teacher_Assigned.query.filter_by(
        staff_id=current_user.staff_id, 
        class_name=class_name
    ).first()
    
    if not has_access:
        flash("You are not allocated as an instructor for this class division.", "danger")
        return redirect(url_for('teacher_overview', staff_id=current_user.staff_id))
        
    # 2. Fetch all teachers assignments to populate the sidebar menu accordion
    assignments = Teacher_Assigned.query.filter_by(staff_id=current_user.staff_id).all()
    
    # 3. Pull the student roster registered for this specific class name configuration
    students = Student.query.filter_by(class_name=class_name).order_by(Student.roll_no).all()
    
    return render_template(
        'teacher_class_roster.html', 
        assignments=assignments, 
        class_name=class_name, 
        students=students
    )


@app.route("/api/get_subjects_and_exams/<class_name>")
@login_required
def get_subjects_and_exams(class_name):
    assignments = Teacher_Assigned.query.filter_by( staff_id=current_user.staff_id, class_name=class_name).all()    
    subjects_list = []
    for a in assignments:
        sub = Subject.query.get(a.subject_id)
        if sub:
            subjects_list.append({'id': sub.subject_id, 'name': sub.subject_name})            
    # Fetch all active exams configured in the system
    exams = Exams.query.all()
    exams_list = [{'id': e.exam_id, 'name': e.exam_name} for e in exams]
    
    return jsonify({
        'subjects': subjects_list,
        'exams': exams_list
    })


# 3. Load Student Roster & Existing Marks onto the Grid
@app.route("/api/load_grade_sheet", methods=['POST'])
@login_required
def load_grade_sheet():
    data = request.get_json()
    class_name = data.get('class_name')
    subject_id = data.get('subject_id')
    exam_id = data.get('exam_id')
    
    # Query all students registered in that specific class
    students = Student.query.filter_by(class_name=class_name).order_by(Student.roll_no).all()
    
    sheet_records = []
    for s in students:
        # Cross-reference with our new safe admission_no target in the Marks table
        existing_mark = Marks.query.filter_by(
            admission_no=s.admission_no,
            subject_id=subject_id,
            exam_id=exam_id
        ).first()
        
        sheet_records.append({
            'admission_no': s.admission_no,
            'roll_no': s.roll_no,
            'name': s.name,
            'marks_obtained': existing_mark.marks_obtained if existing_mark else None,
            'is_saved': True if existing_mark else False  # Drives the green border display
        })
        
    return jsonify({'students': sheet_records})



# 4. One-Click Bulk Save (The Live Grid Upsert Loop)
@app.route("/grades/save", methods=['POST'])
@login_required
def save_grades():
    class_name = request.form.get('class_name')
    subject_id = request.form.get('subject_id')
    exam_id = request.form.get('exam_id')
    
    # Fetch all students in this class to map incoming dynamic input fields
    students = Student.query.filter_by(class_name=class_name).all()
    
    try:
        for s in students:
            # Reconstruct the dynamic name parameter string from our frontend form
            input_field_key = f"marks_{s.admission_no}"
            submitted_score = request.form.get(input_field_key)
            
            if submitted_score is not None and submitted_score.strip() != "":
                score = float(submitted_score)
                
                # Check if it's an Update or a fresh Insert
                mark_record = Marks.query.filter_by(
                    admission_no=s.admission_no,
                    subject_id=subject_id,
                    exam_id=exam_id
                ).first()
                
                if mark_record:
                    mark_record.marks_obtained = score
                else:
                    new_mark = Marks(
                        admission_no=s.admission_no,
                        subject_id=subject_id,
                        exam_id=exam_id,
                        marks_obtained=score
                    )
                    db.session.add(new_mark)
                    
        db.session.commit()
        flash("Excel grade sheet updates committed successfully!", "success")
    except Exception as e:
        db.session.rollback()
        flash("Critical transactional error occurred while updating marks.", "danger")
        
    return redirect(url_for('teacher_dashboard', staff_id=current_user.staff_id))


# 5. Advanced Feature: Bulk Parse External Excel Sheet
@app.route("/grades/upload", methods=['POST'])
@login_required
def upload_excel_grades():
    if 'excel_file' not in request.files:
        flash("No file stream detected.", "danger")
        return redirect(url_for('teacher_dashboard', staff_id=current_user.staff_id))
        
    file = request.files['excel_file']
    if file.filename == '':
        flash("No file selected.", "danger")
        return redirect(url_for('teacher_dashboard', staff_id=current_user.staff_id))
        
    if file and (file.filename.endswith('.xlsx') or file.filename.endswith('.xls')):
        try:
            # Read the spreadsheet using Pandas
            df = pd.read_excel(file)
            
            # Required formatting validation check
            required_headers = ['admission_no', 'subject_id', 'exam_id', 'marks_obtained']
            if not all(column in df.columns for column in required_headers):
                flash("Template layout error. Please verify file column headers match.", "danger")
                return redirect(url_for('teacher_dashboard', staff_id=current_user.staff_id))
            
            records_processed = 0
            for index, row in df.iterrows():
                adm_no = str(row['admission_no']).strip()
                sub_id = str(row['subject_id']).strip()
                ex_id = int(row['exam_id'])
                score = float(row['marks_obtained'])
                
                # Verify student background existence before adding data blindly
                student_exists = Student.query.filter_by(admission_no=adm_no).first()
                if not student_exists:
                    continue # Skip invalid entries gracefully
                    
                mark_record = Marks.query.filter_by(
                    admission_no=adm_no,
                    subject_id=sub_id,
                    exam_id=ex_id
                ).first()
                
                if mark_record:
                    mark_record.marks_obtained = score
                else:
                    new_mark = Marks(
                        admission_no=adm_no,
                        subject_id=sub_id,
                        exam_id=ex_id,
                        marks_obtained=score
                    )
                    db.session.add(new_mark)
                records_processed += 1
                
            db.session.commit()
            flash(f"Success! Imported data logs for {records_processed} students at once.", "success")
            
        except Exception as e:
            db.session.rollback()
            flash("Parsing execution failure. Make sure data formats are completely numeric.", "danger")
            
    return redirect(url_for('teacher_dashboard', staff_id=current_user.staff_id))

#Now the class teacher routes below


@app.route("/dashboard/classteacher/<staff_id>")
@login_required
def classteacher_dashboard(staff_id):
    # Security Guard: Ensure teachers can only access their own dashboard
    if current_user.staff_id != staff_id or current_user.role != "TEACHER":
        flash("Unauthorized access attempt.", "danger")
        return redirect(url_for('login', role="teacher"))
        
    # Double-check they actually are a registered Class Teacher
    managed_class = ClassTeacher.query.filter_by(staff_id=staff_id).first()
    if not managed_class:
        flash("You are not currently assigned as a Class Teacher.", "warning")
        return redirect(url_for('teacher_dashboard'))
        
    # Set session values to keep the layout sidebar active and operational
    session['is_class_teacher'] = True
    session['managed_class_name'] = managed_class.class_name
    
    # Gather workspace telemetry indicators for the dashboard cards
    class_target = managed_class.class_name
    total_students = Student.query.filter_by(class_name=class_target).count()
    total_subjects = Subject.query.count()
    total_exams = Exams.query.count()
    
    return render_template(
        'classteacher_dashboard.html', class_name=class_target, student_count=total_students, subject_count=total_subjects, exam_count=total_exams)
    

# 1. Class Roster View & Virtual Aggregate Matrix Engine
@app.route("/dashboard/class-teacher/roster")
@login_required
def class_teacher_roster():
    if not session.get('is_class_teacher'):
        flash("Access restricted to designated Class Teachers.", "warning")
        return redirect(url_for('teacher_dashboard'))

    class_target = session.get('managed_class_name')
    
    # Fetch all students enrolled in this specific class division group
    students = Student.query.filter_by(class_name=class_target).order_by(Student.roll_no).all()
    
    # Pull all subjects and marks records linked to students inside this classroom
    student_ids = [s.admission_no for s in students]
    all_marks = Marks.query.filter(Marks.admission_no.in_(student_ids)).all()
    subjects = Subject.query.all()
    exams = Exams.query.all()

    # Map marks data matrix maps cleanly for on-the-fly JavaScript rendering loops
    marks_matrix = {}
    for m in all_marks:
        if m.admission_no not in marks_matrix:
            marks_matrix[m.admission_no] = {}
        if m.subject_id not in marks_matrix[m.admission_no]:
            marks_matrix[m.admission_no][m.subject_id] = {}
        marks_matrix[m.admission_no][m.subject_id][m.exam_id] = m.marks_obtained

    return render_template(
        'class_teacher_roster.html',
        students=students,
        subjects=subjects,
        exams=exams,
        marks_json=json.dumps(marks_matrix),
        class_name=class_target
    )


@app.route("/dashboard/teacher/student/edit/<string:admission_no>", methods=['POST'])
@login_required
def edit_student_info(admission_no):
    if current_user.role != "TEACHER":
        flash("Unauthorized administrative action.", "danger")
        return redirect(url_for('class_teacher_roster'))
        
    student = Student.query.get_or_404(admission_no)
    
    # Extract all updated form values matching your grid layout keys
    updated_admission = request.form.get('admission_no', '').strip().upper()
    updated_roll = request.form.get('roll_no', '').strip()
    updated_name = request.form.get('name', '').strip()
    updated_dob = request.form.get('dob', '').strip()
    updated_academic_year = request.form.get('academic_year', '').strip()
    
    # Validation: Mandatory Fields check
    if not updated_admission or not updated_name:
        flash("Admission Number and Student Full Name are strictly required fields.", "warning")
        return redirect(url_for('class_teacher_roster'))
        
    try:
        # 1. 🔍 GLOBAL UNIQUENESS CHECK: Admission Number
        if updated_admission != student.admission_no:
            adm_conflict = Student.query.filter_by(admission_no=updated_admission).first()
            if adm_conflict:
                flash(f"Conflict: Admission No '{updated_admission}' is already assigned to another student in the school.", "danger")
                return redirect(url_for('class_teacher_roster'))
        
        # 2. 🔍 LOCAL UNIQUENESS CHECK: Roll Number inside this specific classroom branch
        if updated_roll and updated_roll != str(student.roll_no):
            roll_conflict = Student.query.filter_by(class_name=student.class_name, roll_no=updated_roll).first()
            if roll_conflict:
                flash(f"Conflict: Roll Number '{updated_roll}' is already taken inside Class {student.class_name}.", "danger")
                return redirect(url_for('class_teacher_roster'))
                
        # 3. Apply updates to the model attributes
        student.admission_no = updated_admission
        student.name = updated_name
        student.roll_no = int(updated_roll) if updated_roll else None
        student.dob = updated_dob if updated_dob else None  # Handled as string or Date type based on your schema config
        student.academic_year = updated_academic_year if updated_academic_year else None
        
        db.session.commit()
        flash(f"Records for {student.name} updated successfully!", "success")
        
    except Exception as e:
        db.session.rollback()
        flash(f"An error occurred while syncing records: {str(e)}", "danger")
        
    return redirect(url_for('class_teacher_roster'))

# 2. Bulk Excel-Style Student Registration Interface Route
@app.route("/dashboard/class-teacher/bulk-students", methods=['GET', 'POST'])
@login_required
def class_teacher_bulk_students():
    if not session.get('is_class_teacher'):
        flash("Unauthorized entry administrative profile permissions required.", "danger")
        return redirect(url_for('teacher_dashboard'))

    class_target = session.get('managed_class_name')

    if request.method == 'POST':
        # Retrieve arrays from tabular form fields
        adm_nos = request.form.getlist('admission_no[]')
        roll_nos = request.form.getlist('roll_no[]')
        names = request.form.getlist('name[]')
        dobs = request.form.getlist('dob[]')
        acad_years = request.form.getlist('academic_year[]')

        inserted_count = 0
        skipped_count = 0

        # Loop over rows submitted via the dynamic grid spreadsheet layout
        for i in range(len(names)):
            adm_no = adm_nos[i].strip().upper() if i < len(adm_nos) else ""
            name = names[i].strip() if i < len(names) else ""
            
            # Skip completely empty rows gracefully
            if not adm_no or not name:
                continue

            # Validation Guard: Prevent duplication crashes against primary keys
            existing_student = Student.query.filter_by(admission_no=adm_no).first()
            if existing_student:
                skipped_count+=1
                continue

            # Safely handle integers or nulls for the classroom roll numbers
            roll_val = None
            if i < len(roll_nos) and roll_nos[i].strip():
                try:
                    roll_val = int(roll_nos[i].strip())
                    # Quick unique check for roll numbers within this class
                    if Student.query.filter_by(class_name=class_target, roll_no=roll_val).first():
                        skipped_count+=1
                        continue
                except ValueError:
                    pass

            # Handle Date structure formats safely
            dob_val = None
            if i < len(dobs) and dobs[i].strip():
                try:
                    from datetime import datetime
                    dob_val = datetime.strptime(dobs[i].strip(), '%Y-%m-%d').date()
                except ValueError:
                    pass

            acad_yr = acad_years[i].strip() if i < len(acad_years) else "2026"

            # Create clean data rows mapping straight into your Student schema
            new_student = Student(
                admission_no=adm_no,
                roll_no=roll_val,
                name=name,
                dob=dob_val,
                academic_year=acad_yr,
                class_name=class_target
            )
            db.session.add(new_student)
            inserted_count+=1

        if inserted_count > 0:
            try:
                db.session.commit()
                flash(f"Successfully enrolled {inserted_count} new student profiles into Class {class_target}!", "success")
            except Exception:
                db.session.rollback()
                flash("A database error occurred during batch transaction verification.", "danger")
        
        if skipped_count > 0:
            flash(f"Skipped {skipped_count} row records due to Admission/Roll number uniqueness conflicts.", "warning")

        return redirect(url_for('class_teacher_roster'))

    return render_template('class_teacher_bulk.html', class_name=class_target)

# 3. Report Card Single Student Data Fetcher
@app.route("/dashboard/class-teacher/report-card")
@login_required
def class_teacher_report_card():
    if not session.get('is_class_teacher'):
        flash("Unauthorized entry.", "danger")
        return redirect(url_for('teacher_dashboard'))

    class_target = session.get('managed_class_name')
    students = Student.query.filter_by(class_name=class_target).order_by(Student.name).all()
    return render_template('class_teacher_report_card.html', students=students)

@app.route("/dashboard/class-teacher/student-report-data/<admission_no>")
@login_required
def student_report_data(admission_no):
    if not session.get('is_class_teacher'):
        return {"error": "Unauthorized Access"}, 403

    class_target = session.get('managed_class_name')
    student = Student.query.filter_by(admission_no=admission_no, class_name=class_target).first_or_404()

    marks_records = db.session.query(
        Subject.subject_name,
        Exams.exam_name,
        Marks.marks_obtained
    ).join(Subject, Marks.subject_id == Subject.subject_id)\
     .join(Exams, Marks.exam_id == Exams.exam_id)\
     .filter(Marks.admission_no == admission_no).all()

    report_data = []
    for record in marks_records:
        report_data.append({
            "subject": record.subject_name,
            "exam": record.exam_name,
            "score": record.marks_obtained
        })

    return {
        "student": {
            "name": student.name,
            "admission_no": student.admission_no,
            "roll_no": student.roll_no if student.roll_no else "-",
            "academic_year": student.academic_year if student.academic_year else "2026",
            "class_name": student.class_name
        },
        "records": report_data
    }


#for all the below is general routes for everyone

@app.route("/reset-request", methods=['GET', 'POST'])
def request_reset():
    if request.method == 'POST':
        form_role = request.form.get('role')
        form_email = request.form.get('email')
        db_role = "PRINCIPAL" if form_role == "principal" else "TEACHER"
        user = Staff.query.filter_by(email=form_email, role=db_role).first()        
        if not user:
            flash("This email address is not registered under the selected account type.", "danger")
            return render_template('reset_request.html')            
        token = serializer.dumps(user.email, salt='secure-password-reset-salt')
        reset_url = url_for('reset_verification', token=token, _external=True)        
        try:
            msg = Message("Password Reset Verification Link", sender=app.config['MAIL_USERNAME'], recipients=[user.email])
            msg.body = f"Hello {user.name or 'Staff Member'},\n\nClick the link below to set up a new password:\n{reset_url}\n\nThis link will automatically expire in 5 minutes."
            mail.send(msg)            
            flash("A secure password reset link has been dispatched to your email address.", "success")
        except Exception as e:
            print(f"Email dispatch error: {str(e)}")
            flash("Failed to send the email. Please try again.", "danger")
        return redirect(url_for('request_reset'))
    return render_template('reset_request.html')


@app.route('/reset-password/<token>', methods=['GET','POST'])
def reset_verification(token):
    try:
        email_from_token=serializer.loads(token,salt='secure-password-reset-salt',max_age=300)
    except SignatureExpired:
        flash("The password reset token has expired. Please request a new link.", "danger")
        return redirect(url_for('request_reset'))
    except BadTimeSignature:
        return redirect(url_for('request_reset'))
    
    if request.method == 'POST':
        new_password=request.form.get('new_password')
        confirm_password=request.form.get('confirm_password')
        if new_password != confirm_password:
            flash("Passwords do not match. Please re-enter both entries.", "danger")
            return render_template('reset_password.html')
        user=Staff.query.filter_by(email=email_from_token).first()
        if user: 
            user.password=generate_password_hash(new_password)
            db.session.commit()
            flash("Your password has been successfully updated you can now log into it","success")
            return redirect(url_for('login',role="TEACHER"))
        flash("No user account with this email exists.","danger")
        return redirect(url_for('request_reset'))
    return render_template('reset_password.html')


def generate_staff_id(role):
    prefix="T"
    if role == "TEACHER":
        prefix = "T"
    if role == "PRINCIPAL":
        principal = Staff.query.filter_by(role="PRINCIPAL").first()
        if principal:
            flash("A Principal account already exists.", "error")
            return redirect(url_for("register_staff"))
        else:
            prefix="P"
    last_staff = (Staff.query.filter(Staff.staff_id.like(f"{prefix}%")).order_by(Staff.staff_id.desc()).first())
    if last_staff:
        last_number = int(last_staff.staff_id[1:])
        new_number = last_number + 1
    else:
        new_number = 1
    return f"{prefix}{new_number:04d}"

@app.route("/register-staff",methods=["GET","POST"])
def register_staff():
    if request.method=="POST":
        name=request.form["name"].strip()
        email=request.form["email"].strip().lower()
        password=request.form["password"]
        role=request.form["role"]
        if len(name)==0:
            flash("Name cannot be empty.","error")
            return redirect(url_for("register_staff"))
        existing_user=Staff.query.filter_by(email=email).first()
        if existing_user:
            flash("Email already registered.","error")
            return redirect(url_for("register_staff"))

        if role == "PRINCIPAL":
            existing_principal = Staff.query.filter_by(role="PRINCIPAL").first()
            if existing_principal:
                flash("An administrative Principal account already exists in this system.", "error")
                return redirect(url_for("register_staff"))

        password_pattern=r"^(?=.*[a-z])(?=.*[A-Z])(?=.*\d)(?=.*[@$!%*?&^#()_+\-=\[\]{};':\"\\|,.<>\/]).{8,}$"
        if not re.match(password_pattern,password):
            flash("Password must contain at least 8 characters including uppercase, lowercase, number and special character.","error")          
            return redirect(url_for("register_staff"))

        hashed_password=generate_password_hash(password)
        staff_id=generate_staff_id(role)
        new_staff=Staff(staff_id=staff_id, name=name, email=email, password=hashed_password, role=role, status="Active")
        db.session.add(new_staff)
        db.session.flush()
        
        if role == "PRINCIPAL":
            new_principal_entry = Principal(staff_id=staff_id)
            db.session.add(new_principal_entry)
            
        try:
            db.session.commit()
            flash("Registration Successful.", "success")
            return redirect(url_for("login", role=role))
        except Exception:
            db.session.rollback()
            flash("A transactional error occurred during enrollment registration.", "error")
            return redirect(url_for("register_staff"))
    return render_template("staff_register.html")


