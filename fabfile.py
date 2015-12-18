import os
import imp
import jinja2
import datetime
import getpass

from fabric.api import (
        run,
        local,
        put,
        env,
        settings,
        get,
        prompt,
        sudo,
)

base_path = os.path.dirname(os.path.abspath(__file__))


######################################################
#
# Configuration
#
######################################################

def _import_conf():
    conf_path = None
    exported_conf_path = os.getenv('ONYFAB_CONF_PATH', None)
    if not exported_conf_path:
        # default path
        default_conf_path = os.path.join(base_path, 'conf.py')
        if os.path.isfile(default_conf_path):
            conf_path = default_conf_path
        else:
            conf_path = prompt('Please, specify the conf file path: ', default='../config/fab-conf.py')
            print 'export ONYFAB_CONF_PATH="{}"'.format(conf_path)
    else:
        conf_path = exported_conf_path
    env.conf = imp.load_source('conf', conf_path)


def _init():
    _import_conf()
    _update_passwords()
    env.hosts = [env.conf.hosts[env.conf.default_host]]
    user(env.conf.default_user)
    host(env.conf.default_host)


def _update_passwords():
    for key in env.conf.users.keys():
        user = env.conf.users[key]
        if 'password' in env.conf.users[key] and env.conf.users[key].get('password') is None:
            p = getpass.getpass(prompt='{} password: '.format(user['username']))
            env.conf.users[key]['password'] = p


######################################################
#
# Server connection
#
######################################################

def host(host_key):
    # append host
    env.hosts += [env.conf.hosts[host_key]]


def user(user_key):
    env.user = env.conf.users[user_key]['username']
    try:
        env.password = env.conf.users[user_key]['password']
    except:
        pass
    try:
        env.key_filename = env.conf.users[user_key]['key_filename']
    except:
        pass


def root():
    user('root')


def robot():
    user('robot')


######################################################
#
# Update Server sw
#
######################################################

def init_server():
    fab_log('init')
    root()
    update_os()
    install_packages()
    create_robot_user()
    copy_robot_ssh_keys()
    init_git()
    create_virtualenv()
    update_virtualenv()
    syncdb()
    create_gunicorn_script()
    create_supervisor_conf()
    restart_gunicorn()
    create_apache_conf()
    restart_apache()


def update_os():
    fab_log('update_os')
    run('apt-get update')
    run('apt-get upgrade')


def package_installed(pkg_name):
    fab_log('package_installed')
    cmd_f = 'dpkg-query -l "%s" | grep -q ^.i'
    cmd = cmd_f % (pkg_name)
    with settings(warn_only=True):
        result = run(cmd)
    return result.succeeded


def install_package(pkg_name):
    fab_log('install_package')
    run('apt-get --force-yes --yes install %s' % (pkg_name))


def install_packages():
    fab_log('install packages')
    for package in env.conf.packages:
        print "check package: %s" % package
        if not package_installed(package):
            print "not installed"
            install_package(package)
        else:
            print "OK"


def install_virtualenv():
    fab_log('install_virtualenv')
    root()
    run('pip install virtualenv')


######################################################
#
# Server users
#
######################################################

def create_robot_user():
    fab_log('create_robot_user')
    root()
    with settings(warn_only=True):
        run('groupadd --system %(group)s' % env.conf.users['robot'])
        password = env.conf.users['robot'].get('password')
        if password:
            cmd = "useradd  -g %(group)s -d /home/%(username)s -m -s /bin/bash -p $(echo %(password)s | " \
                  "openssl passwd -1 -stdin) %(username)s" % env.conf.users['robot']
        else:
            cmd = "useradd  -g %(group)s -d /home/%(username)s -m -s /bin/bash %(username)s" % env.conf.users['robot']
        print cmd
        run(cmd)


def copy_robot_ssh_keys():
    fab_log('copy_robot_ssh_keys')
    with settings(warn_only=True):
        run('mkdir /home/%(username)s/.ssh -p' % env.conf.users['robot'])
    put(env.conf.users['robot']['id_rsa'], '/home/%(username)s/.ssh/id_rsa' % env.conf.users['robot'])
    run('chmod 600  /home/%(username)s/.ssh/id_rsa' % env.conf.users['robot'])
    put(env.conf.users['robot']['id_rsa.pub'], '/home/%(username)s/.ssh/id_rsa.pub' % env.conf.users['robot'])
    run('chown %(username)s:%(group)s /home/%(username)s/.ssh/id_rsa' % env.conf.users['robot'])
    run('chown %(username)s:%(group)s /home/%(username)s/.ssh/id_rsa.pub' % env.conf.users['robot'])
    with settings(warn_only=True):
        run('rm /home/%(username)s/.ssh/authorized_keys' % env.conf.users['robot'])
    run('cat /home/%(username)s/.ssh/id_rsa.pub >> /home/%(username)s/.ssh/authorized_keys' % env.conf.users['robot'])
    run('chown %(username)s:%(group)s /home/%(username)s/.ssh/authorized_keys' % env.conf.users['robot'])
    run('touch /home/%(username)s/.ssh/known_hosts' % env.conf.users['robot'])
    run('chown %(username)s:%(group)s /home/%(username)s/.ssh/known_hosts' % env.conf.users['robot'])


######################################################
#
# GIT
#
######################################################

def init_git():
    fab_log('init_git')
    root()
    with settings(warn_only=True):
        # create project path
        run('mkdir -p %s' % env.conf.project_path)
        # change owner
        run('chown -R %s.%s %s' % (
                env.conf.users['robot']['username'],
                env.conf.users['robot']['group'],
                env.conf.project_path))
        robot()
        cmds = ['cd %s' % env.conf.project_path,
                'git clone %s' % env.conf.git_repo,
                ]
        run('; '.join(cmds))
        cmds = [
                'cd %s' % env.conf.code_path,
                'git config user.email %s' % env.conf.git_user_email,
                'git config user.name %s' % env.conf.git_user_name
        ]
        run('; '.join(cmds))


def update_code(branch=None):
    fab_log('update_code')
    if not branch:
        if hasattr(env.conf, 'git_default_branch'):
            branch = env.conf.git_default_branch
        else:
            branch = 'master'

    robot()
    # create branch if it's necesary
    with settings(warn_only=True):
        cmds = ['cd %s' % env.conf.code_path,
                'git checkout -b %s' % branch,
                ]
        run('; '.join(cmds))
    # get code
    cmds = [
            'cd %s' % env.conf.code_path,
            'git checkout %s' % branch,
            'git pull origin %s' % branch,
    ]
    run('; '.join(cmds))
    update_virtualenv()
    migrate_db()
    collectstatic()
    restart_gunicorn()
    restart_apache()


def purge_code():
    fab_log('purge_code')
    robot()
    s = env.conf.git_repo
    git_dir_name = s.split(".")[-2].split('/')[-1]
    cmds = [
            'cd %s' % env.conf.project_path,
            'rm -rf %s' % git_dir_name,
    ]
    run('; '.join(cmds))
    init_git()
    update_code()


######################################################
#
# Virtualenv
#
######################################################

def create_virtualenv():
    fab_log('create_virtualenv')
    robot()
    print env.conf.virtualenv_python_path
    try:
        python_path = "-p %s" % env.conf.virtualenv_python_path
    except:
        python_path = ''
    with settings(warn_only=True):
        run('virtualenv %s %s' % (python_path, env.conf.virtaulenv_path))


def update_virtualenv():
    fab_log('update_virtualenv')
    robot()
    run('more %s' % env.conf.virtualenv_requirements_path)
    cmds = ['source %s' % env.conf.virtualenv_activate,
            'pip install -r %s' % env.conf.virtualenv_requirements_path,
            ]
    run('; '.join(cmds))


######################################################
#
# Django DB
#
######################################################

def syncdb():
    fab_log('syncdb')
    update_code()
    robot()
    cmds = ['source %s' % env.conf.virtualenv_activate,
            'cd %s' % env.conf.code_path,
            'python manage.py syncdb --noinput --settings=%s' % env.conf.django_settings,
            ]
    run('; '.join(cmds))


def migrate_db():
    fab_log('migrate_db')
    robot()
    cmds = ['source %s' % env.conf.virtualenv_activate,
            'cd %s' % env.conf.code_path,
            'python manage.py migrate --settings=%s' % env.conf.django_settings,
            ]
    run('; '.join(cmds))


def createsuperuser():
    fab_log('create_superuser')
    robot()
    cmds = ['source %s' % env.conf.virtualenv_activate,
            'cd %s' % env.conf.code_path,
            'python manage.py createsuperuser --settings=%s' % env.conf.django_settings,
            ]
    run('; '.join(cmds))


def create_dumpdata_script():
    fab_log('create_dumpdata_script')
    robot()
    # local
    templateLoader = jinja2.FileSystemLoader(searchpath=os.path.dirname(os.path.abspath(__file__)))
    templateEnv = jinja2.Environment(loader=templateLoader)
    template = templateEnv.get_template("templates/dumpdata.sh.jinja")
    print template.render(env.conf.get_globals())
    local_path = "/tmp/dumpdata.sh"
    with settings(warn_only=True):
        local("rm %s" % local_path)
    text_file = open(local_path, "w")
    text_file.write(template.render(env.conf.get_globals()))
    text_file.close()
    # remote
    print env.conf.bin_path
    run('mkdir -p %s' % env.conf.bin_path)
    with settings(warn_only=True):
        run("rm %s" % env.conf.dumpdata_sh_path)
    put(local_path, env.conf.dumpdata_sh_path)
    run("chmod 744 %s" % env.conf.dumpdata_sh_path)


######################################################
#
# Static
#
######################################################

def collectstatic():
    fab_log('collectstatic')
    robot()
    cmds = ['source %s' % env.conf.virtualenv_activate,
            'cd %s' % env.conf.code_path,
            'python manage.py collectstatic --noinput --settings=%s' % env.conf.django_settings,
            ]
    run('; '.join(cmds))


######################################################
#
# Web Servers
#
######################################################


def create_gunicorn_script():
    fab_log('create_gunicorn_script')
    robot()
    # local
    templateLoader = jinja2.FileSystemLoader(searchpath=os.path.dirname(os.path.abspath(__file__)))
    templateEnv = jinja2.Environment(loader=templateLoader)
    template = templateEnv.get_template("templates/start.sh.jinja")
    print template.render(env.conf.get_globals())
    local_path = "/tmp/start_gunicorn.sh"
    with settings(warn_only=True):
        local("rm %s" % local_path)
    text_file = open(local_path, "w")
    text_file.write(template.render(env.conf.get_globals()))
    text_file.close()
    # remote
    print env.conf.gunicorn_start_sh_dir
    run('mkdir -p %s' % env.conf.gunicorn_start_sh_dir)
    with settings(warn_only=True):
        run("rm %s" % env.conf.gunicorn_start_sh_path)
    put(local_path, env.conf.gunicorn_start_sh_path)
    run("chmod 744 %s" % env.conf.gunicorn_start_sh_path)


def create_supervisor_conf():
    fab_log('create_supervisor_conf')
    root()
    print base_path
    templateLoader = jinja2.FileSystemLoader(searchpath=base_path)
    templateEnv = jinja2.Environment(loader=templateLoader)
    template = templateEnv.get_template("templates/supervisor.conf.jinja")
    print template.render(env.conf.get_globals())
    local_path = "/tmp/supervisor.conf"
    with settings(warn_only=True):
        local("rm %s" % local_path)
    text_file = open(local_path, "w")
    text_file.write(template.render(env.conf.get_globals()))
    text_file.close()
    robot()
    run('mkdir -p %s' % env.conf.logs_dir)
    root()
    with settings(warn_only=True):
        run("rm %s" % env.conf.supervisor_conf)
    put(local_path, env.conf.supervisor_conf)
    run('supervisorctl reread')
    run('supervisorctl update')


def restart_gunicorn():
    fab_log('restart_gunicorn')
    root()
    run('supervisorctl restart %s' % env.conf.name)


def create_apache_conf():
    fab_log('create_apache_conf')
    root()
    templateLoader = jinja2.FileSystemLoader(searchpath=os.path.dirname(os.path.abspath(__file__)))
    templateEnv = jinja2.Environment(loader=templateLoader)
    template = templateEnv.get_template("templates/apache.jinja")
    print template.render(env.conf.get_globals())
    local_path = "/tmp/apache.conf"
    with settings(warn_only=True):
        local("rm %s" % local_path)
    text_file = open(local_path, "w")
    text_file.write(template.render(env.conf.get_globals()))
    text_file.close()
    remote_path = '/etc/apache2/sites-available/%s.conf' % env.conf.name
    with settings(warn_only=True):
        run("rm %s" % remote_path)
    put(local_path,  remote_path)
    # create symbolic link in the sites-enabled folder
    root()
    run('a2ensite %s' % env.conf.name)
    run('a2enmod proxy')
    run('a2enmod rewrite')
    run('a2enmod proxy_http')
    restart_apache()


def restart_apache():
    fab_log('restart_apache')
    root()
    run('service apache2 restart')


def create_nginx_conf():
    fab_log('create_nginx_conf')
    root()
    templateLoader = jinja2.FileSystemLoader(searchpath=os.path.dirname(os.path.abspath(__file__)))
    templateEnv = jinja2.Environment(loader=templateLoader)
    template = templateEnv.get_template("templates/nginx.jinja")
    print template.render(env.conf.get_globals())
    local_path = "/tmp/nginx.conf"
    with settings(warn_only=True):
        local("rm %s" % local_path)
    text_file = open(local_path, "w")
    text_file.write(template.render(env.conf.get_globals()))
    text_file.close()
    remote_path = '/etc/nginx/sites-available/%s' % env.conf.name
    with settings(warn_only=True):
        run("rm %s" % remote_path)
    put(local_path,  remote_path)
    # create symbolic link in the sites-enabled folder
    with settings(warn_only=True):
        run('ln -s /etc/nginx/sites-available/%s /etc/nginx/sites-enabled/%s' % (env.conf.name, env.conf.name))
    put('passwords/htpasswd', '/etc/nginx/.htpasswd')
    run('chown -R %s.%s /etc/nginx/.htpasswd' % (env.conf.gunicorn_user, env.conf.gunicorn_group))
    root()
    restart_nginx()


def restart_nginx():
    fab_log('restart_nginx')
    root()
    run('service nginx restart')


######################################################
#
# POSTGRES
#
######################################################

dump_file_path_template = '/tmp/{}-dump.sql'
ubuntu_postgres_user = 'cd /tmp; sudo -u postgres {cmd}'
ubuntu_psql_cmd = ubuntu_postgres_user.format(cmd='psql -c "{cmd}"')


def psql_drop_local_db(db_name):
    fab_log('psql_drop_local_db')
    with settings(warn_only=True):
        cmd = "dropdb {db_name}".format(db_name=db_name)
        cmd = ubuntu_postgres_user.format(cmd=cmd)
        local(cmd)
        cmd = "dropuser {db_user}".format(db_user=env.conf.postgres_db_user)
        cmd = ubuntu_postgres_user.format(cmd=cmd)
        local(cmd)


def psql_create_local_db(db_name):
    fab_log('psql_create_local_db')

    with settings(warn_only=True):
        cmds = []
        cmd = "CREATE DATABASE {db_name} ENCODING='UTF8';".format(db_name=db_name)
        cmds.append(ubuntu_psql_cmd.format(cmd=cmd))
        cmd = "create user {db_user} with password '{db_password}';".format(
                db_user=env.conf.postgres_db_user,
                db_password=env.conf.postgres_db_local_password)
        cmds.append(ubuntu_psql_cmd.format(cmd=cmd))
        cmd = "grant all privileges on database {db_name} to {db_user};".format(
                db_name=db_name,
                db_user=env.conf.postgres_db_user)
        cmds.append(ubuntu_psql_cmd.format(cmd=cmd))
        local(";".join(cmds))


def psql_load_dump_local_db(db_name, dumpfile_path):
    fab_log('psql_load_dump_local_db')

    cmd = " psql {db_name} < {dumpfile_path}".format(dumpfile_path=dumpfile_path,
                                                     db_name=db_name)
    cmd = ubuntu_postgres_user.format(cmd=cmd)
    local(cmd)


def psql_remote_to_local():
    psql_remote_to_local_with_name(env.conf.postgres_db_name)


def psql_remote_to_local_with_name(db_name):
    fab_log('psql_remote_to_local')

    # create dump file remotely
    remote_path = dump_file_path_template.format(db_name)
    psg_create_sql_file('remote', remote_path)
    run('ls -l {}'.format(remote_path))
    remote_compressed_file = '{}.tar.gz'.format(remote_path)
    compress_file(remote_path, remote_compressed_file, 'remote')
    run('ls -l {}'.format(remote_compressed_file))

    # copy to local path
    local_path = dump_file_path_template.format(db_name)
    local_compressed_file = '{}.tar.gz'.format(local_path)
    get(remote_path=remote_compressed_file, local_path=local_compressed_file)
    local('ls -l {}'.format(local_compressed_file))
    extract_file(local_compressed_file, local_path, 'local')

    psql_drop_local_db(db_name)
    psql_create_local_db(db_name)
    psql_load_dump_local_db(db_name, local_path)


def psg_create_sql_file(location, destiny_path):
    fab_log('psg_create_sql_file({})'.format(location))

    if location == 'remote':
        root()
        with settings(warn_only=True):
            run('rm {}'.format(destiny_path))
        cmd = 'pg_dump -C -f {dump_file_path} -h localhost -U {user} {db_name}'.format(
                dump_file_path=destiny_path,
                user=env.conf.postgres_db_user,
                db_name=env.conf.postgres_db_name)
        run(cmd)


######################################################
#
# Miscelanea
#
######################################################

def compress_file(source, destiny, location):
    fab_log('compress_file({source}, {destiny}, {location})'
            .format(source=source, destiny=destiny, location=location))
    compress_or_extract_file(source, destiny, location, 'compress')


def extract_file(source, destiny, location):
    fab_log('extract_file({source}, {destiny}, {location})'
            .format(source=source, destiny=destiny, location=location))
    compress_or_extract_file(source, destiny, location, 'extract')


def compress_or_extract_file(source, destiny, location, mode):
    source_path = os.path.dirname(source)
    destiny_path = os.path.dirname(destiny)
    source_file_name = os.path.basename(source)
    destiny_file_name = os.path.basename(destiny)

    cmds = ['cd {source_path}'.format(source_path=source_path)]
    if mode == 'compress':
        cmds.append(
            'tar -zcvf {destiny_file_name} {source_file_name}'.format(source_file_name=source_file_name,
                                                                      destiny_file_name=destiny_file_name)
        )

    if mode == 'extract':
        cmds.append(
            'tar -zxvf {source_file_name}'.format(source_file_name=source_file_name)
        )

    if source_path != destiny_path:
        cmds.append(
            'cp -f {destiny_file_name} {destiny}'.format(destiny_file_name=destiny_file_name,
                                                         destiny=destiny))

    if location == 'remote':
        run(' && '.join(cmds))
    if location == 'local':
        local(' && '.join(cmds))


def check():
    fab_log('check')
    run("uptime")


def run_manage_cmd(manage_cmd):
    fab_log('run_manage_cmd - {}'.format(manage_cmd))
    robot()
    cmds = ['source %s' % env.conf.virtualenv_activate,
            'cd %s' % env.conf.code_path,
            'python manage.py {manage_cmd} --settings={settings}'.format(settings=env.conf.django_settings,
                                                                         manage_cmd=manage_cmd)
            ]
    run('; '.join(cmds))


def create_backup():
    root()
    dir_name = datetime.datetime.now().strftime('%Y-%m-%d_%H-%M-%S')
    # sqlite
    local_base_path = os.path.join(env.conf.backups_local_path, dir_name)
    local("mkdir -p {local_base_path}".format(local_base_path=local_base_path))
    remote_path = env.conf.sqlite_production_path
    get(remote_path=remote_path, local_path=local_base_path)
    # media
    media_local_path = os.path.join(local_base_path, 'media')
    remote_media_path = env.conf.media_path
    get(remote_path=remote_media_path, local_path=media_local_path)
    # compress
    local('tar -zcvf {archive_name}.tar.gz {directory_name}'.format(archive_name=local_base_path,
                                                                    directory_name=local_base_path))
    local('rm -rf {local_base_path}'.format(local_base_path=local_base_path))


def fab_log(fun_name):
    print ""
    print ""
    print "********************************************************"
    print "*                     %s" % fun_name
    print "********************************************************"

_init()
