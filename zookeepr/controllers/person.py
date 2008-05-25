import datetime

from formencode import validators, Invalid
from formencode.schema import Schema
from formencode.variabledecode import NestedVariables
import sqlalchemy

from zookeepr.lib.auth import PersonAuthenticator, retcode
from zookeepr.lib.base import *
from zookeepr.lib.mail import *
from zookeepr.lib.validators import BaseSchema
from zookeepr.model import Person, PasswordResetConfirmation

from zookeepr.lib.base import *
from zookeepr.lib.crud import Read, Update, List
from zookeepr.lib.auth import SecureController, AuthRole, AuthFunc
from zookeepr import model
from zookeepr.model.core.domain import Role
from zookeepr.model.core.tables import person_role_map
from sqlalchemy import and_


class AuthenticationValidator(validators.FancyValidator):
    def validate_python(self, value, state):
        l = PersonAuthenticator()
        r = l.authenticate(value['email_address'], value['password'])
        if r == retcode.SUCCESS:
            pass
        elif r == retcode.FAILURE:
            raise Invalid("Your sign-in details are incorrect.", value, state)
        elif r == retcode.TRY_AGAIN:
            raise Invalid("A problem occurred during sign in; please try again later.", value, state)
        elif r == retcode.INACTIVE:
            raise Invalid("You haven't yet confirmed your registration, please refer to your email for instructions on how to do so.", value, state)
        else:
            raise RuntimeError, "Unhandled authentication return code: '%r'" % r


class ExistingPersonValidator(validators.FancyValidator):
    def validate_python(self, value, state):
        persons = state.query(Person).filter_by(email_address=value['email_address']).first()
        if persons == None:
            raise Invalid("""Your sign-in details are incorrect; try the
                'Forgotten your password' link below or sign up for a new
                person.""", value, state)


class LoginValidator(BaseSchema):
    email_address = validators.String(not_empty=True)
    password = validators.String(not_empty=True)

    chained_validators = [ExistingPersonValidator(), AuthenticationValidator()]


class ForgottenPasswordSchema(BaseSchema):
    email_address = validators.String(not_empty=True)

    chained_validators = [ExistingPersonValidator()]


class PasswordResetSchema(BaseSchema):
    password = validators.String(not_empty=True)
    password_confirm = validators.String(not_empty=True)

    chained_validators = [validators.FieldsMatch('password', 'password_confirm')]


# FIXME: merge with registration controller validator and move to validators
class NotExistingPersonValidator(validators.FancyValidator):
    def validate_python(self, value, state):
        person = state.query(Person).filter_by(email_address=value['email_address']).first()
        if person is not None:
            raise Invalid("This person already exists.  Please try signing in first.", value, state)


class PersonSchema(Schema):
    email_address = validators.String(not_empty=True)
    firstname = validators.String(not_empty=True)
    lastname = validators.String(not_empty=True)
    address1 = validators.String(not_empty=True)
    address2 = validators.String()
    city = validators.String(not_empty=True)
    state = validators.String()
    postcode = validators.String(not_empty=True)
    country = validators.String(not_empty=True)
    company = validators.String()
    phone = validators.String()
    mobile = validators.String()
    password = validators.String(not_empty=True)
    password_confirm = validators.String(not_empty=True)

    chained_validators = [NotExistingPersonValidator(), validators.FieldsMatch('password', 'password_confirm')]


class NewPersonSchema(BaseSchema):
    person = PersonSchema()

    pre_validators = [NestedVariables]


class PersonController(SecureController, Read, Update, List):
    individual = 'person'
    model = model.Person
    permissions = {'view': [AuthFunc('is_same_id'), AuthRole('organiser')],
                   'roles': [AuthRole('organiser')],
                   'index': [AuthRole('organiser')]
                   }
    permissions = {'ALL': True}


    def signin(self):
        defaults = dict(request.POST)
        errors = {}

        if defaults:
            result, errors = LoginValidator().validate(defaults, self.dbsession)

            if not errors:
                # do the authorisation here or in validator?
                # get person
                # check auth
                # set session cookies
                person = self.dbsession.query(Person).filter_by(email_address=result['email_address']).one()
                if person:
                    # at least one Person matches, save it
                    session['signed_in_person_id'] = person.id
                    session.save()

                    # Redirect to original URL if it exists
                    if 'sign_in_redirect' in session:
                        redirect_to(str(session['sign_in_redirect']))

                    # return to the registration status
		    # (while registrations are open)
                #    redirect_to('/registration/status')

                    # return home
                    redirect_to('home')

        return render_response('person/signin.myt', defaults=defaults, errors=errors)

    def signout(self):
        defaults = dict(request.POST)
	if defaults:
            # delete and invalidate the session
            session.delete()
            session.invalidate()
            # return home
            redirect_to('home')
	return render_response('person/signout.myt', defaults=None, errors={})

    def confirm(self, id):
        """Confirm a registration with the given ID.

        `id` is a md5 hash of the email address of the registrant, the time
        they regsitered, and a nonce.

        """
        r = self.dbsession.query(Person).filter_by(url_hash=id).all()

        if len(r) < 1:
            abort(404)

        r[0].activated = True

        self.dbsession.update(r[0])
        self.dbsession.flush()

        return render_response('person/confirmed.myt')

    def forgotten_password(self):
        """Action to let the user request a password change.

        GET returns a form for emailing them the password change
        confirmation.

        POST checks the form and then creates a confirmation record:
        date, email_address, and a url_hash that is a hash of a
        combination of date, email_address, and a random nonce.

        The email address must exist in the person database.

        The second half of the password change operation happens in
        the ``confirm`` action.
        """
        defaults = dict(request.POST)
        errors = {}

        if defaults:
            result, errors = ForgottenPasswordSchema().validate(defaults, self.dbsession)

            if not errors:
                c.conf_rec = PasswordResetConfirmation(result['email_address'])
                self.dbsession.save(c.conf_rec)
                try:
                    self.dbsession.flush()
                except sqlalchemy.exceptions.SQLError, e:
                    self.dbsession.clear()
                    # FIXME exposes sqlalchemy!
                    return render_response('person/in_progress.myt')

                email(c.conf_rec.email_address,
                    render('person/confirmation_email.myt', fragment=True))
                return render_response('person/password_confirmation_sent.myt')
        return render_response('person/forgotten_password.myt', defaults=defaults, errors=errors)


    def reset_password(self, url_hash):
        """Confirm a password change request, and let the user change
        their password.

        `url_hash` is a hash of the email address, with which we can
        look up the confuirmation record in the database.

        If `url_hash` doesn't exist, 404.

        If `url_hash` exists and the date is older than 24 hours,
        warn the user, offer to send a new confirmation, and delete the
        confirmation record.

        GET returns a form for setting their password, with their email
        address already shown.

        POST checks that the email address (in the session, not in the
        form) is part of a valid person record (again).  If the record
        exists, then update the password, hashed.  Report success to the
        user.  Delete the confirmation record.

        If the record doesn't exist, throw an error, delete the
        confirmation record.
        """
        crecs = self.dbsession.query(PasswordResetConfirmation).filter_by(url_hash=url_hash).all()
        if len(crecs) == 0:
            abort(404)

        c.conf_rec = crecs[0]

        now = datetime.datetime.now(c.conf_rec.timestamp.tzinfo)
        delta = now - c.conf_rec.timestamp
        if delta > datetime.timedelta(24, 0, 0):
            # this confirmation record has expired
            self.dbsession.delete(c.conf_rec)
            self.dbsession.flush()
            return render_response('person/expired.myt')

        # now process the form
        defaults = dict(request.POST)
        errors = {}

        if defaults:
            result, errors = PasswordResetSchema().validate(defaults, self.dbsession)

            if not errors:
                persons = self.dbsession.query(Person).filter_by(email_address=c.conf_rec.email_address).all()
                if len(persons) == 0:
                    raise RuntimeError, "Person doesn't exist %s" % c.conf_rec.email_address

                # set the password
                persons[0].password = result['password']
                # also make sure the person is activated
                persons[0].activated = True
                
                # delete the conf rec
                self.dbsession.delete(c.conf_rec)
                self.dbsession.flush()

                return render_response('person/success.myt')

        # FIXME: test the process above
        return render_response('person/reset.myt', defaults=defaults, errors=errors)


    def new(self):
        """Create a new person.

        Non-CFP persons get created through this interface.

        See ``cfp.py`` for more person creation code.
        """
        defaults = dict(request.POST)
        errors = {}

        if defaults:
            result, errors = NewPersonSchema().validate(defaults, self.dbsession)

            if not errors:
                c.person = Person()
                # update the objects with the validated form data
                for k in result['person']:
                    setattr(c.person, k, result['person'][k])
                self.dbsession.save(c.person)
                self.dbsession.flush()

                email(c.person.email_address,
                    render('person/new_person_email.myt', fragment=True))
                return render_response('person/thankyou.myt')

        return render_response('person/new.myt',
                               defaults=defaults, errors=errors)


    def index(self):
        r = AuthRole('organiser')
        if self.logged_in():
            if not r.authorise(self):
                redirect_to(action='view', id=session['signed_in_person_id'])
        else:
            abort(403)

        return super(PersonController, self).index()

    def view(self):
        c.registration_status = request.environ['paste.config']['app_conf'].get('registration_status')
        if self.logged_in():
            roles = self.dbsession.query(Role).all()
            for role in roles:
                r = AuthRole(role.name)
                if r.authorise(self):
                    setattr(c, 'is_%s_role' % role.name, True)

        return super(PersonController, self).view()

    def roles(self):
        """ Lists and changes the person's roles. """

        td = '<td valign="middle">'
        res = ''
        res += '<b>'+self.obj.firstname+' '+self.obj.lastname+'</b><br>'
        data = dict(request.POST)
        if data:
          role = int(data['role'])
          act = data['commit']
          if act not in ['Grant', 'Revoke']: raise "foo!"
          r = self.dbsession.query(Role).filter_by(id=role).one()
          res += '<p>' + act + ' ' + r.name + '.'
          if act=='Revoke':
            person_role_map.delete(and_(
              person_role_map.c.person_id == self.obj.id,
              person_role_map.c.role_id == role)).execute()
          if act=='Grant':
            person_role_map.insert().execute(person_id = self.obj.id,
                                                            role_id = role)


        res += '<table>'
        for r in self.dbsession.query(Role).all():
          res += '<tr>'
          # can't use AuthRole here, because it may be out of date
          has = len(person_role_map.select(whereclause = 
            and_(person_role_map.c.person_id == self.obj.id,
              person_role_map.c.role_id == r.id)).execute().fetchall())

          if has>1:
            # this can happen if two people Grant at once, or one person
            # does a Grant and reloads/reposts.
            res += td + 'is %d times' % has
            has = 1
          else:
            res += td+('is not', 'is')[has]
          res += td+r.name

          res += td+h.form(h.url())
          res += h.hidden_field('role', r.id)
          res += h.submit(('Grant', 'Revoke')[has])
          res += h.end_form()

        res += '</table>'

        return Response(res)

    def is_same_id(self, *args):
        return self.obj.id == session['signed_in_person_id']
