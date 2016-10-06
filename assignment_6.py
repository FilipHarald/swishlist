import datetime
import time
from collections import defaultdict

from flask import Flask, jsonify, json, redirect, render_template, request, session, url_for
from flask_wtf import Form
from wtforms import StringField, SubmitField, IntegerField, SelectField, DateTimeField
from wtforms.validators import DataRequired, ValidationError, Regexp, Length

app = Flask(__name__)
app.secret_key = 's3cr3t'
storage_path_users = 'storage/users.json'
storage_path_groups = 'storage/groups.json'
storage_path_expenses = 'storage/expenses.json'
api_prefix = '/api'


# API
# API - Users
@app.route(api_prefix + '/users/')
def get_users():
    return jsonify(get_resources(storage_path_users))


@app.route(api_prefix + '/users/<string:phone>/')
def api_get_user(phone):
    return jsonify(get_user(phone))


@app.route(api_prefix + '/users/<string:phone>/expenses/')
def get_user_expenses(phone):
    all_expenses = get_resources(storage_path_expenses)
    user_expenses = [expense for expense in all_expenses if expense['payer']['phone'] == phone]
    return jsonify(user_expenses)


@app.route(api_prefix + '/users/<string:phone>/groups/')
def api_get_user_groups(phone):
    return jsonify(get_user_groups(phone))


# API - Expenses
@app.route(api_prefix + '/expenses/')
def api_get_expenses():
    return jsonify(get_expenses())


@app.route(api_prefix + '/expenses/<int:created>/')
def api_get_expense(created):
    return jsonify(get_expense(created))


# API - Groups
@app.route(api_prefix + '/groups/')
def get_groups():
    return jsonify(get_resources(storage_path_groups))


@app.route(api_prefix + '/groups/<int:group_id>/')
def api_get_group(group_id):
    return jsonify(get_group(group_id))


@app.route(api_prefix + '/groups/<int:group_id>/expenses/')
def api_get_group_expenses(group_id):
    return jsonify(get_group_expenses(group_id))


@app.route(api_prefix + '/groups/<int:group_id>/users/')
def api_get_group_users(group_id):
    return jsonify(get_group_users(group_id))


# UI
@app.route('/')
def index(form=None):
    if not form:
        form = UserForm()
    return render_template('index.html',
                           groups=get_resources(storage_path_groups)['groups'],
                           form=form,
                           errors=session.get('errors'),
                           user=session['user'])


@app.route('/sign-out/')
def sign_out():
    session['user'] = None
    return redirect(url_for('index'))


@app.route('/users/', methods=['GET'])
def show_users():
    return render_template('users.html',
                           users=get_resources(storage_path_users),
                           form=UserForm())


@app.route('/users/', methods=['POST'])
def create_user():
    form = UserForm(request.form)
    if form.validate_on_submit():
        user = {'name': form.name.data, 'phone': form.phone.data}
        store_resource(storage_path_users, user)
        session['user'] = user
        return redirect(url_for('show_user', phone=user['phone']))
    return index(form=form)


@app.route('/users/<string:phone>/', methods=['GET'])
def show_user(phone):
    return render_template('profile.html',
                           user=get_user(phone),
                           groups=get_user_groups(phone))


@app.route('/expenses/', methods=['GET'])
def show_expenses():
    expense_data = {'expenses': get_expenses()}
    format_expenses(expense_data['expenses'])
    return render_template('expenses.html',
                           expense_data=expense_data,
                           form=ExpenseForm())


@app.route('/expenses/', methods=['POST'])
def create_expense():
    form = ExpenseForm(request.form)
    users = get_resources(storage_path_users)
    form.payer.choices = [(user['phone'], user['name']) for user in users]
    if form.validate_on_submit():
        expense = {'amount': form.amount.data,
                   'payer': {'phone': form.payer.data,
                             'link': url_for('api_get_user', phone=form.payer.data, _external=True)},
                   'text': form.text.data,
                   'group': {'id': session['group_id'],
                             'link': url_for('api_get_group', group_id=session['group_id'], _external=True)},
                   'created': int(form.created.data.strftime('%s'))}
        store_resource(storage_path_expenses, expense)
        return redirect(url_for('show_group', group_id=session['group_id']))
    return show_group(group_id=session['group_id'], expense_form=form)


@app.route('/expenses/<int:created>/')
def show_expense(created):
    expense = get_expense(created)
    expense['group']['name'] = get_group(expense['group']['id'])['name']
    expense['date'] = time.strftime('%Y-%m-%d', time.localtime(expense['created']))
    return render_template('expense.html',
                           expense=expense)


@app.route('/expenses/<int:created>/edit', methods=['GET', 'POST'])
def edit_expense(created):
    if request.method == 'POST':
        expense_form = ExpenseForm(request.form)
        users = get_resources(storage_path_users)
        expense_form.payer.choices = [(user['phone'], user['name']) for user in users]
        if expense_form.validate_on_submit():
            update_expense(expense_form, old_created=created)
            return redirect(url_for('show_expense', created=int(expense_form.created.data.strftime('%s'))))
    expense = get_expense(created)
    expense_form = ExpenseForm()
    expense_form.amount.data = expense['amount']
    expense_form.created.data = datetime.datetime.fromtimestamp(expense['created'])
    expense_form.text.data = expense['text']
    users = get_group_users(expense['group']['id'])
    expense_form.payer.choices = [(user['phone'], user['name']) for user in users]
    return render_template('edit_expense.html',
                           expense=expense,
                           expense_form=expense_form)


@app.route('/expenses/<int:created>/delete', methods=['GET'])
def delete_expense(created):
    remove_expense(created)
    return redirect(url_for('show_expenses'))


@app.route('/groups/', methods=['GET'])
def show_groups():
    return render_template('groups.html',
                           groups=get_resources(storage_path_groups)['groups'],
                           group_form=GroupForm())


@app.route('/groups/', methods=['POST'])
def create_group():
    form = GroupForm(request.form)
    if form.validate_on_submit():
        group = {'name': form.name.data}
        store_resource(storage_path_groups, group)
        return redirect(url_for('show_groups'))
    return redirect(url_for('show_groups'))


@app.route('/groups/<int:group_id>/')
def show_group(group_id, expense_form=None):
    session['group_id'] = group_id
    expense_data = {'expenses': get_group_expenses(group_id)}
    expense_data['tot_amount'] = sum(expense['amount'] for expense in expense_data['expenses'])
    format_expenses(expense_data['expenses'])
    users = calculate_debt_data(get_group_users(group_id), expense_data)
    add_user_form = AddUserForm()
    add_user_form.user_phone.choices = [(user['phone'], user['name']) for user in get_not_group_users(group_id)]
    if not expense_form and users:
        expense_form = ExpenseForm()
        expense_form.payer.choices = [(user['phone'], user['name']) for user in users]
    return render_template('group.html',
                           group=get_group(group_id),
                           users=users,
                           expense_data=expense_data,
                           expense_form=expense_form,
                           add_user_form=add_user_form)


@app.route('/groups/<int:group_id>/users', methods=['POST'])
def add_user_to_group(group_id):
    form = AddUserForm(request.form)
    form.user_phone.choices = [(user['phone'], user['name']) for user in get_not_group_users(group_id)]
    if form.validate_on_submit():
        store_user_to_group(form.user_phone.data, group_id)
        return redirect(url_for('show_group', group_id=group_id))
    return redirect(url_for('show_group', group_id=group_id))


# UI - helper methods
def format_expenses(expenses):
    for expense in expenses:
        expense['date'] = time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(expense['created']))


def calculate_debt_data(users, expense_data):
    if not users:
        return None
    avg_expense = int(expense_data['tot_amount'] / len(users))
    users_expenses = defaultdict(lambda: 0)
    for expense in expense_data['expenses']:
        users_expenses[expense['payer']['phone']] += expense['amount']
    for user in users:
        user_delta = avg_expense - users_expenses[user['phone']]
        if user_delta > 0:
            user['debt'] = 'Owes debt collector ' + str(user_delta)
        elif user_delta == 0:
            user['debt'] = 'Nothing to pay, nothing to collect'
        else:
            user['debt'] = 'DEBT COLLECTOR'
    return users


# UI - errors
@app.errorhandler(404)
def page_not_found(error):
    return render_template('errors/page_not_found.html'), 404


# UI - form helper methods
def no_inline_digits_check(form, field):
    if any(char.isdigit() for char in field.data):
        raise ValidationError('Field cannot contain any numbers.')


# UI - forms
class UserForm(Form):
    name = StringField("Name",
                       validators=[
                                   DataRequired(),
                                   no_inline_digits_check],
                       render_kw={"placeholder": "Name"})
    phone = StringField(validators=[DataRequired(),
                                    Regexp('[0-9]{4}[-][0-9]{6}', message=
                                    'Phone number must be in the form "xxxx-xxxxxx" where x can only be digits.')],
                        render_kw={"placeholder": "Phone"})
    submit = SubmitField('Submit')


class GroupForm(Form):
    name = StringField('Name:',
                       validators=[DataRequired(), Length(min=1, max=70)],
                       render_kw={"placeholder": "Name of the group"})
    submit = SubmitField('Submit')


class ExpenseForm(Form):
    amount = IntegerField('Amount:',
                          validators=[DataRequired()],
                          render_kw={"placeholder": "What was the amount of the expense?"})
    payer = SelectField('User:',
                        validators=[DataRequired()],
                        render_kw={"placeholder": "Who had the expense?"})
    text = StringField('Text:',
                       validators=[DataRequired()],
                       render_kw={"placeholder": "What was the expense for?"})
    created = DateTimeField('When:',
                            validators=[DataRequired()],
                            format='%Y-%m-%dT%H:%M',
                            render_kw={"placeholder": "When was the expense?"})
    submit = SubmitField('Submit')


class AddUserForm(Form):
    user_phone = SelectField('User:', validators=[DataRequired()])
    submit = SubmitField('Submit')


# Storage
def store_resource(storage_path, resource):
    if storage_path == storage_path_groups:
        store_group(storage_path, resource)
    else:
        with open(storage_path, "r+") as file:
            data = json.load(file)
            file.seek(0)
            data.append(resource)
            json.dump(data, file, indent=4)
            file.truncate()


def store_group(storage_path, group):
    data = get_resources(storage_path)
    id_counter = data['current_id'] + 1
    data['current_id'] = id_counter
    group['id'] = id_counter
    group['users'] = []
    data['groups'].append(group)
    write_resources(storage_path, data)


def store_user_to_group(user_phone, group_id):
    data = get_resources(storage_path_groups)
    group = next(group for group in data['groups'] if group['id'] == group_id)
    group['users'].append({'phone': user_phone,
                           'link': url_for('api_get_user', phone=user_phone, _external=True)})
    write_resources(storage_path_groups, data)


def get_resources(storage_path):
    with open(storage_path, "r") as file:
        return json.load(file)


def write_resources(storage_path, data):
    with open(storage_path, "w") as file:
        json.dump(data, file, indent=4)


def get_user(phone):
    users = get_resources(storage_path_users)
    user_data = next(user for user in users if user['phone'] == phone)
    return user_data


def get_user_groups(phone):
    groups_data = get_resources(storage_path_groups)
    user_groups = [group for group in groups_data['groups']
                   if any(user['phone'] == phone for user in group['users'])]
    return user_groups


def get_group(group_id):
    groups = get_resources(storage_path_groups)['groups']
    group_data = next(group for group in groups if group['id'] == group_id)
    return group_data


def get_group_users(group_id):
    all_groups = get_resources(storage_path_groups)['groups']
    all_users = get_resources(storage_path_users)
    group_data = next(group for group in all_groups if group['id'] == group_id)
    group_users = []
    for member in group_data['users']:
        group_users.append(next(user for user in all_users if user['phone'] == member['phone']))
    return group_users


def get_not_group_users(group_id):
    all_groups = get_resources(storage_path_groups)['groups']
    all_users = get_resources(storage_path_users)
    group_data = next(group for group in all_groups if group['id'] == group_id)
    group_users = []
    for user in all_users:
        if not any(user for member in group_data['users'] if member['phone'] == user['phone']):
            group_users.append(user)
    return group_users


def get_expense(created):
    expenses = get_resources(storage_path_expenses)
    expense_data = next(expense for expense in expenses if expense['created'] == created)
    return expense_data


def update_expense(expense_form, old_created):
    expense = get_expense(old_created)
    expense['amount'] = expense_form.amount.data
    expense['created'] = int(expense_form.created.data.strftime('%s'))
    expense['payer']['phone'] = expense_form.payer.data
    expense['payer']['link'] = url_for('api_get_user', phone=expense_form.payer.data, _external=True)
    expense['text'] = expense_form.text.data
    replace_expense(expense, old_created)


def replace_expense(expense, old_created):
    expenses = get_resources(storage_path_expenses)
    expenses[:] = [exp for exp in expenses if exp['created'] != old_created]
    expenses.append(expense)
    write_resources(storage_path_expenses, expenses)


def remove_expense(created):
    expenses = get_resources(storage_path_expenses)
    expenses[:] = [exp for exp in expenses if exp['created'] != created]
    write_resources(storage_path_expenses, expenses)


def get_expenses():
    return get_resources(storage_path_expenses)


def get_group_expenses(group_id):
    all_expenses = get_resources(storage_path_expenses)
    group_expenses = [expense for expense in all_expenses if expense['group']['id'] == group_id]
    return group_expenses

app.run()
