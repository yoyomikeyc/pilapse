import os
import datetime
import pytz
from pytz import timezone

from flask import Flask
from flask import g
from flask import redirect
from flask import request
from flask import session
from flask import url_for, abort, render_template, flash, send_from_directory
from functools import wraps
import config

from pw import encode_pw
from db_model import create_tables, Roles, Users, Relationships, Messages, Settings, Sessions, States #,KeyValuePairTypes

import psutil
import pi_psutil

# create a flask application - this ``app`` object will be used to handle
# inbound requests, routing them to the proper 'view' functions, etc
app = Flask(__name__)
    
# flask provides a "session" object, which allows us to store information across
# requests (stored by default in a secure cookie).  this function allows us to
# mark a user as being logged-in by setting some values in the session data:
def auth_user(user):
    session['logged_in'] = True
    session['user_id'] = user.id
    session['username'] = user.username
    # TODO this needs to be moved outside of the cookie
    session['is_admin'] = is_admin()
    flash('You are logged in as %s' % (user.username))

# get the user from the session
def get_current_user():
    if session.get('logged_in'):
        return Users.get(Users.id == session['user_id'])

# Is the user from the session an admin
def is_admin():
    user = get_current_user()
    return user.is_role("admin")


# Decorator to mark an endpint as requiring admin privledges
# TODO: Load from DB, not cookie
def admin_required(f):
    @wraps(f)
    def inner(*args, **kwargs):
        if not session.get('is_admin'):
            abort(404)
        ret_val = f(*args, **kwargs)
        return ret_val
    return inner

# view decorator which indicates that the requesting user must be authenticated
# before they can access the view.  it checks the session to see if they're
# logged in, and if not redirects them to the login view.
def login_required(f):
    @wraps(f)
    def inner(*args, **kwargs):
        if not session.get('logged_in'):
            return redirect(url_for('login'))
        try:
            ret_val = f(*args, **kwargs)
        except Users.DoesNotExist:
            return redirect(url_for('login'))
        return ret_val
    return inner

# given a template and a SelectQuery instance, render a paginated list of
# objects from the query inside the template
def object_list(template_name, qr, var_name='object_list', **kwargs):
    kwargs.update(
        page=int(request.args.get('page', 1)),
        pages=qr.count() / 20 + 1)
    kwargs[var_name] = qr.paginate(kwargs['page'])
    return render_template(template_name, **kwargs)

# retrieve a single object matching the specified query or 404 -- this uses the
# shortcut "get" method on model, which retrieves a single object or raises a
# DoesNotExist exception if no matching object exists
# http://charlesleifer.com/docs/peewee/peewee/models.html#Model.get)
def get_object_or_404(model, *expressions):
    try:
        return model.get(*expressions)
    except model.DoesNotExist:
        abort(404)

# custom template filter -- flask allows you to define these functions and then
# they are accessible in the template -- this one returns a boolean whether the
# given user is following another user.
@app.template_filter('is_following')
def is_following(from_user, to_user):
    return from_user.is_following(to_user)

# Request handlers -- these two hooks are provided by flask and we will use them
# to create and tear down a database connection on each request.
@app.before_request
def before_request():
    g.db = database
    g.db.connect()

@app.after_request
def after_request(response):
    g.db.close()
    return response

# views -- these are the actual mappings of url to view function
@app.route('/')
def homepage():
    # depending on whether the requesting user is logged in or not, show them
    # either the public timeline or their own private timeline
    if session.get('logged_in'):
        return latest_video()
    else:
        return login()

@app.route('/latest_video/')
@login_required
def latest_video():
    sessions = Sessions.select().where(Sessions.ended_at.is_null(False))

    stats = get_system_stats()
    return object_list('latest_video.html', sessions, 'session_list', stats=stats, Settings=Settings, Sessions=Sessions)

@app.route('/public/')
def public_timeline():
    # simply display all messages, newest first
    messages = Messages.select().order_by(Messages.pub_date.desc())
    return object_list('public_messages.html', messages, 'message_list', Settings=Settings)

@app.route('/videos/<path:path>', methods=['GET'])
def videos(path):
    static_url_path=Settings.get_value_by_key('encoder_video_path')
    if not os.path.isfile(os.path.join(static_url_path, path)):
        path = os.path.join(path, 'index.html')
        
    return send_from_directory(static_url_path, path)
    

@app.route('/join/', methods=['GET', 'POST'])
def join():
    if request.method == 'POST' and request.form['username']:
        try:
            with database.atomic():
                # Attempt to create the user. If the username is taken, due to the
                # unique constraint, the database will raise an IntegrityError.
                user_role=Roles.get(Roles.name == "user")
                user = Users.create(
                    username=request.form['username'],
                    password=encode_pw(request.form['password']),
                    email=request.form['email'],
                    join_date=datetime.datetime.now(),
                    role=user_role
                )
            # mark the user as being 'authenticated' by setting the session vars
            auth_user(user)
            return redirect(url_for('homepage'))

        except IntegrityError:
            flash('That username is already taken')

    return render_template('join.html', Settings=Settings)

@app.route('/login/', methods=['GET', 'POST'])
def login():
    if request.method == 'POST' and request.form['username']:
        try:
            pw_hash = encode_pw(request.form['password'])
            user = Users.get(
                (Users.username == request.form['username']) &
                (Users.password == pw_hash))
        except Users.DoesNotExist:
            flash('The password entered is incorrect')
        else:
            auth_user(user)
            return redirect(url_for('homepage'))

    return render_template('login.html', Settings=Settings)

@app.route('/logout/')
def logout():
    session.pop('logged_in', None)
    flash('You were logged out')
    return redirect(url_for('homepage'))

@app.route('/about/')
def about():
    return render_template('about.html', Settings=Settings)

def get_system_stats():
    stats={}
    TIME_FORMAT = "%Y-%m-%d, %H:%M:%S %Z"
    
    # Get last update of video
    video_path = Settings.get_value_by_key('encoder_video_path') + '/' + Settings.get_value_by_key('encoder_video_output_filename')

    system_tz = Settings.get_value_by_key('general_timezone')
    try:
        update_time = os.path.getmtime(video_path)
        update_time =  pytz.utc.localize(datetime.datetime.utcfromtimestamp(update_time))
        update_time = update_time.astimezone(timezone(system_tz))
        update_time_str = update_time.strftime(TIME_FORMAT)
    except FileNotFoundError:
        update_time_str = "None"
    stats['update_time'] = update_time_str
    # Get the current time
    now =  pytz.utc.localize(datetime.datetime.utcnow()).astimezone(timezone(system_tz))
    stats['now'] = now.strftime(TIME_FORMAT)
    
    # Get capture status
    capture = Settings.get_value_by_key('capture_enable')
    if capture:
        capture='<font size="4" color="red">Recording</font>'
    else:
        capture='<font size="4" color="black">Stopped</font>'
    stats['capture']=capture
    # Current session info
    stats['current_session'] = Sessions.select().where(Sessions.ended_at.is_null()).order_by(Sessions.started_at.desc()).first()
    stats['image_num'] = States.get_image_num()

    # Temp Status
    tempc = pi_psutil.get_cpu_temperature()
    color = "green"
    if tempc > 70:
        color = "orange"
    if tempc > 80:
        color = "red"
    stats['tempc'] = tempc
    stats['tempc_str'] = '<font color="%s">%2.1f C</font>' % (color, tempc)

    # RAM
    ram = psutil.virtual_memory()
    stats['ram_total'] = "%dMB" % (ram.total / 2**20)       # MiB.
    stats['ram_used'] = "%dMB" % (ram.used / 2**20)
    ram_free = (ram.free / 2**20)
    color = "green"
    if ram_free < 64:
        color = "orange"
    if ram_free < 32:
        color = "red"
    stats['ram_free'] = '<font color="%s">%dMB</font>' % (color, ram_free)
    stats['ram_percent_used'] = "%2.1f%%" % (ram.percent)

    # DISK
    disk = psutil.disk_usage('/')
    stats['disk_total'] = "%2.1fGB" % (disk.total / 2**30)     # GiB.
    stats['disk_used'] = "%2.1fGB" % (disk.used / 2**30)
    disk_free = (disk.free / 2**30)
    color = "green"
    if disk_free < 1:
        color = "orange"
    if disk_free < 0.5:
        color = "red"
    stats['disk_free'] = '<font color="%s">%2.1fGB</font>' % (color, disk_free)
    stats['disk_percent_used'] = "%2.1f%%" % (disk.percent)
    
    return stats
        
@app.route('/admin/')
@login_required
@admin_required
def admin():
    # Get forms for all settings and make available to render
    all_settings = Settings.select().order_by(Settings.key)
    forms = [ {'key': s.key, 'title': config.get_title(s.key), 'help': config.get_desc(s.key), 'form': config.get_form_html(s.key, s.value) } for s in all_settings]
    # render page
    return render_template('admin.html', stats=get_system_stats(), setting_forms=forms, Settings=Settings)

@app.route('/settings/', methods=['GET', 'POST'])
@login_required
@admin_required
def settings():
    if request.method == 'POST':
        for k,v in request.form.items():
            Settings.upsert_kvp(k,v)
        update_flask_settings()
        flash('Updated')

    return admin()


@app.route('/following/')
@login_required
def following():
    user = get_current_user()
    return object_list('user_following.html', user.following(), 'user_list', Settings=Settings)

@app.route('/followers/')
@login_required
def followers():
    user = get_current_user()
    return object_list('user_followers.html', user.followers(), 'user_list', Settings=Settings)

@app.route('/users/')
def user_list():
    users = Users.select().order_by(Users.username)
    return object_list('user_list.html', users, 'user_list', Settings=Settings)

@app.route('/users/<username>/')
def user_detail(username):
    # using the "get_object_or_404" shortcut here to get a user with a valid
    # username or short-circuit and display a 404 if no user exists in the db
    user = get_object_or_404(Users, Users.username == username)

    # get all the users messages ordered newest-first -- note how we're accessing
    # the messages -- user.message_set.  could also have written it as:
    # Messages.select().where(Messages.user == user)
    messages = user.messages.order_by(Messages.pub_date.desc())
    return object_list('user_detail.html', messages, 'message_list', user=user, Settings=Settings)

@app.route('/users/<username>/follow/', methods=['POST'])
@login_required
def user_follow(username):
    user = get_object_or_404(Users, Users.username == username)
    try:
        with database.atomic():
            Relationships.create(
                from_user=get_current_user(),
                to_user=user)
    except IntegrityError:
        pass

    flash('You are following %s' % user.username)
    return redirect(url_for('user_detail', username=user.username))

@app.route('/users/<username>/unfollow/', methods=['POST'])
@login_required
def user_unfollow(username):
    user = get_object_or_404(Users, Users.username == username)
    (Relationships
     .delete()
     .where(
         (Relationships.from_user == get_current_user()) &
         (Relationships.to_user == user))
     .execute())
    flash('You are no longer following %s' % user.username)
    return redirect(url_for('user_detail', username=user.username))

@app.route('/post/', methods=['GET', 'POST'])
@login_required
def post():
    user = get_current_user()
    if request.method == 'POST' and request.form['content']:
        Messages.create(
            user=user,
            content=request.form['content'],
            pub_date=datetime.datetime.now())
        flash('Your message has been created')
        return redirect(url_for('user_detail', username=user.username))

    return render_template('post.html', Settings=Settings)


@app.route('/startCapture', methods=['POST'])
@login_required
@admin_required
def startCapture():
    Settings.upsert_kvp('capture_enable', True)
    flash('Capture started.')
    return redirect(url_for('admin'))

@app.route('/stopCapture', methods=['POST'])
@login_required
@admin_required
def stopCapture():
    Settings.upsert_kvp('capture_enable', False)
    flash('Capture stopped.')

    Sessions.end_session(description=request.form['session_description'])

    return redirect(url_for('admin'))

@app.route('/shutdown', methods=['POST'])
@login_required
@admin_required
def shutdown():
    SHUTDOWN_DELAY=1
    # Shutdown after 1 minute (seconds not possible on pi)
    cmd = "sudo shutdown -t %d" % SHUTDOWN_DELAY
    ret_value = os.system(cmd)
    if not ret_value:
        flash('Success. System shutdown scheduled for %d minute(s) from now.' % SHUTDOWN_DELAY)
    else:
        flash('Error. Failed to schedule system shutdown. Does the process have access?')
    return redirect(url_for('admin'))
                                                                                        
@app.context_processor
def _inject_user():
    try:
        user = get_current_user()
        return {'current_user': user }
    except Users.DoesNotExist:
        return {}

def update_flask_settings():
    debug = Settings.get_value_by_key('webserver_debug')
    secret = Settings.get_value_by_key('webserver_secret')
    
    app.config.update(
        DEBUG=debug,
        SECRET_KEY=secret
    )

    # allow running from the command line
if __name__ == '__main__':
    # Create and seed tables
    create_tables()

    update_flask_settings()
    
    app.run(host="0.0.0.0",
            port=5000
    )
