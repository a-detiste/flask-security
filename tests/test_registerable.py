"""
test_registerable
~~~~~~~~~~~~~~~~~

Registerable tests
"""

import pytest
import re
from flask import Flask
from tests.test_utils import (
    authenticate,
    check_xlation,
    get_form_input_value,
    get_form_input,
    init_app_with_options,
    json_authenticate,
    logout,
)

from flask_security import Security, UserMixin, user_registered, user_not_registered
from flask_security.forms import (
    ConfirmRegisterForm,
    RegisterForm,
    RegisterFormV2,
    StringField,
    _default_field_labels,
)
from flask_security.utils import localize_callback

pytestmark = pytest.mark.registerable()


@pytest.mark.settings(post_register_view="/post_register")
def test_registerable_flag(clients, app, get_message):
    recorded = []

    # Test the register view
    response = clients.get("/register")
    assert b"<h1>Register</h1>" in response.data
    assert re.search(b'<input[^>]*type="email"[^>]*>', response.data)
    assert get_form_input_value(response, "email") is not None
    assert not get_form_input_value(response, "username")

    # Test registering is successful, sends email, and fires signal
    @user_registered.connect_via(app)
    def on_user_registered(app, **kwargs):
        assert isinstance(app, Flask)
        assert isinstance(kwargs["user"], UserMixin)
        assert kwargs["confirm_token"] is None
        assert len(kwargs["form_data"].keys()) > 0

        recorded.append(kwargs["user"])

    data = dict(
        email="dude@lp.com",
        password="battery staple",
        password_confirm="battery staple",
        next="",
    )
    response = clients.post("/register", data=data, follow_redirects=True)

    assert len(recorded) == 1
    assert len(app.mail.outbox) == 1
    assert b"Post Register" in response.data

    logout(clients)

    # Test user can login after registering
    response = authenticate(clients, email="dude@lp.com", password="battery staple")
    assert response.status_code == 302

    logout(clients)

    # Test registering with an existing email
    data = dict(
        email="dude@lp.com", password="password", password_confirm="password", next=""
    )
    response = clients.post("/register", data=data, follow_redirects=True)
    assert get_message("EMAIL_ALREADY_ASSOCIATED", email="dude@lp.com") in response.data

    # Test registering with an existing email but case insensitive
    data = dict(
        email="Dude@lp.com", password="password", password_confirm="password", next=""
    )
    response = clients.post("/register", data=data, follow_redirects=True)
    assert get_message("EMAIL_ALREADY_ASSOCIATED", email="Dude@lp.com") in response.data

    # Test registering with JSON
    data = dict(email="dude2@lp.com", password="horse battery")
    response = clients.post(
        "/register", json=data, headers={"Content-Type": "application/json"}
    )

    assert response.headers["content-type"] == "application/json"
    assert response.json["meta"]["code"] == 200
    assert len(response.json["response"]) == 2
    assert all(k in response.json["response"] for k in ["csrf_token", "user"])

    logout(clients)

    # Test registering with invalid JSON
    data = dict(email="bogus", password="password")
    response = clients.post(
        "/register", json=data, headers={"Content-Type": "application/json"}
    )
    assert response.headers["content-type"] == "application/json"
    assert response.json["meta"]["code"] == 400

    logout(clients)

    # Test ?next param
    data = dict(
        email="dude3@lp.com",
        password="horse staple",
        password_confirm="horse staple",
        next="",
    )

    response = clients.post("/register?next=/page1", data=data, follow_redirects=True)
    assert b"Page 1" in response.data


@pytest.mark.csrf(csrfprotect=True)
def test_form_csrf(app, client):
    # Test that CSRFprotect config catches CSRF requirement at unauth_csrf() decorator.
    # Note that in this case - 400 is returned - though if CSRFprotect isn't enabled
    # then CSRF errors are caught at form.submit time and a 200 with error values
    # is returned.
    response = client.post(
        "/register",
        data=dict(
            email="csrf@example.com",
            password="mypassword",
            password_confirm="mypassword",
        ),
    )
    assert response.status_code == 400
    assert b"The CSRF token is missing" in response.data

    response = client.get("/register")
    csrf_token = get_form_input_value(response, "csrf_token")
    response = client.post(
        "/register",
        data=dict(
            email="csrf@example.com",
            password="mypassword",
            password_confirm="mypassword",
            csrf_token=csrf_token,
        ),
        follow_redirects=False,
    )
    assert response.status_code == 302
    assert response.location == "/"


@pytest.mark.confirmable()
@pytest.mark.app_settings(babel_default_locale="fr_FR")
@pytest.mark.babel()
def test_xlation(app, client, get_message_local):
    # Test form and email translation
    assert check_xlation(app, "fr_FR"), "You must run python setup.py compile_catalog"

    confirmation_token = []

    @user_registered.connect_via(app)
    def on_user_registered(app, **kwargs):
        confirmation_token.append(kwargs["confirmation_token"])

    response = client.get("/register", follow_redirects=True)
    with app.test_request_context():
        # Check header
        assert f'<h1>{localize_callback("Register")}</h1>'.encode() in response.data
        submit = localize_callback(_default_field_labels["register"])
        assert f'value="{submit}"'.encode() in response.data

    response = client.post(
        "/register",
        data={
            "email": "me@fr.com",
            "password": "new strong password",
            "password_confirm": "new strong password",
        },
        follow_redirects=True,
    )
    outbox = app.mail.outbox

    with app.test_request_context():
        assert (
            get_message_local("CONFIRM_REGISTRATION", email="me@fr.com").encode("utf-8")
            in response.data
        )
        assert b"Home Page" in response.data
        assert len(outbox) == 1
        assert (
            localize_callback(app.config["SECURITY_EMAIL_SUBJECT_REGISTER"])
            in outbox[0].subject
        )
        lc = localize_callback(
            'Use <a href="%(confirmation_link)s">this link</a> to confirm your email'
            " address.",
            confirmation_link=f"http://localhost/confirm/{confirmation_token[0]}",
        )
        assert lc in outbox[0].alternatives[0][0]


@pytest.mark.confirmable()
def test_required_password(client, get_message):
    # when confirm required - should not require confirm_password - but should
    # require a password
    data = dict(email="trp@lp.com", password="")
    response = client.post("/register", data=data, follow_redirects=True)
    assert get_message("PASSWORD_NOT_PROVIDED") in response.data

    data = dict(email="trp@lp.com", password="battery staple")
    response = client.post("/register", data=data, follow_redirects=True)
    assert get_message("CONFIRM_REGISTRATION", email="trp@lp.com") in response.data


def test_required_password_confirm(client, get_message):
    response = client.post(
        "/register",
        data={
            "email": "trp@lp.com",
            "password": "password",
            "password_confirm": "notpassword",
        },
        follow_redirects=True,
    )
    assert get_message("RETYPE_PASSWORD_MISMATCH") in response.data

    response = client.post(
        "/register",
        data={"email": "trp@lp.com", "password": "password", "password_confirm": ""},
        follow_redirects=True,
    )
    assert get_message("PASSWORD_NOT_PROVIDED") in response.data


@pytest.mark.confirmable()
@pytest.mark.unified_signin()
@pytest.mark.settings(password_required=False)
def test_allow_null_password(client, get_message):
    # If unified sign in is enabled - should be able to register w/o password
    data = dict(email="trp@lp.com", password="")
    response = client.post("/register", data=data, follow_redirects=True)
    assert get_message("CONFIRM_REGISTRATION", email="trp@lp.com") in response.data


@pytest.mark.unified_signin()
@pytest.mark.settings(password_required=False)
def test_allow_null_password_nologin(client, get_message):
    # If unified sign in is enabled - should be able to register w/o password
    # With confirmable false - should be logged in automatically upon register.
    # But shouldn't be able to perform normal login again
    data = dict(email="trp@lp.com", password="")
    response = client.post("/register", data=data, follow_redirects=True)
    assert b"Welcome trp@lp.com" in response.data
    logout(client)

    # Make sure can't log in
    response = authenticate(client, email="trp@lp.com", password="")
    assert get_message("PASSWORD_NOT_PROVIDED") in response.data

    response = authenticate(client, email="trp@lp.com", password="NoPassword")
    assert get_message("INVALID_PASSWORD") in response.data


@pytest.mark.settings(
    register_url="/custom_register", post_register_view="/post_register"
)
def test_custom_register_url(client):
    response = client.get("/custom_register")
    assert b"<h1>Register</h1>" in response.data

    data = dict(
        email="dude@lp.com",
        password="battery staple",
        password_confirm="battery staple",
        next="",
    )

    response = client.post("/custom_register", data=data, follow_redirects=True)
    assert b"Post Register" in response.data


@pytest.mark.settings(register_user_template="custom_security/register_user.html")
def test_custom_register_template(client):
    response = client.get("/register")
    assert b"CUSTOM REGISTER USER" in response.data


@pytest.mark.settings(send_register_email=False)
def test_disable_register_emails(client, app):
    data = dict(
        email="dude@lp.com", password="password", password_confirm="password", next=""
    )
    client.post("/register", data=data, follow_redirects=True)
    assert not app.mail.outbox


@pytest.mark.two_factor()
@pytest.mark.settings(two_factor_required=True)
def test_two_factor(app, client):
    """If two-factor is enabled, the register shouldn't login, but start the
    2-factor setup.
    """
    data = dict(email="dude@lp.com", password="password", password_confirm="password")
    response = client.post("/register", data=data, follow_redirects=False)
    assert "tf-setup" in response.location

    # make sure not logged in
    response = client.get("/profile")
    assert response.status_code == 302
    assert response.location == "/login?next=/profile"


@pytest.mark.two_factor()
@pytest.mark.settings(two_factor_required=True)
def test_two_factor_json(app, client, get_message):
    data = dict(email="dude@lp.com", password="password", password_confirm="password")
    response = client.post("/register", content_type="application/json", json=data)
    assert response.status_code == 200
    assert response.json["response"]["tf_required"]
    assert response.json["response"]["tf_state"] == "setup_from_login"

    # make sure not logged in
    response = client.get("/profile", headers={"accept": "application/json"})
    assert response.status_code == 401
    assert response.json["response"]["errors"][0].encode("utf-8") == get_message(
        "UNAUTHENTICATED"
    )


@pytest.mark.filterwarnings("ignore:.*The RegisterForm.*:DeprecationWarning")
def test_form_data_is_passed_to_user_registered_signal(app, sqlalchemy_datastore):
    class MyRegisterForm(RegisterForm):
        additional_field = StringField("additional_field")

    app.security = Security(
        app, datastore=sqlalchemy_datastore, register_form=MyRegisterForm
    )

    recorded = []

    @user_registered.connect_via(app)
    def on_user_registered(app, **kwargs):
        assert isinstance(app, Flask)
        assert isinstance(kwargs["user"], UserMixin)
        assert kwargs["confirm_token"] is None
        assert kwargs["confirmation_token"] is None
        assert kwargs["form_data"]["additional_field"] == "additional_data"

        recorded.append(kwargs["user"])

    client = app.test_client()

    data = dict(
        email="dude@lp.com",
        password="password",
        password_confirm="password",
        additional_field="additional_data",
    )
    response = client.post("/register", data=data, follow_redirects=True)

    assert response.status_code == 200
    assert len(recorded) == 1


@pytest.mark.settings(password_complexity_checker="zxcvbn")
@pytest.mark.filterwarnings("ignore:.*The ConfirmRegisterForm.*:DeprecationWarning")
def test_easy_password(app, sqlalchemy_datastore):
    class MyRegisterForm(ConfirmRegisterForm):
        username = StringField("Username")

    app.config["SECURITY_CONFIRM_REGISTER_FORM"] = MyRegisterForm
    security = Security(datastore=sqlalchemy_datastore)
    security.init_app(app)

    client = app.test_client()

    # With zxcvbn
    data = dict(
        email="dude@lp.com",
        username="dude",
        password="mattmatt2",
        password_confirm="mattmatt2",
    )
    response = client.post(
        "/register", json=data, headers={"Content-Type": "application/json"}
    )
    assert response.headers["Content-Type"] == "application/json"
    assert response.status_code == 400
    # Response from zxcvbn
    assert "Repeats like" in response.json["response"]["errors"][0]

    # Test that username affects password selection
    data = dict(
        email="dude@lp.com",
        username="Joe",
        password="JoeTheDude",
        password_confirm="JoeTheDude",
    )
    response = client.post(
        "/register", json=data, headers={"Content-Type": "application/json"}
    )
    assert response.headers["Content-Type"] == "application/json"
    assert response.status_code == 400
    # Response from zxcvbn
    assert (
        "Password not complex enough"
        in response.json["response"]["field_errors"]["password"][0]
    )


@pytest.mark.settings(username_enable=True)
def test_nullable_username(app, client):
    # sqlalchemy datastore uses fsqlav2 which has username as unique and nullable
    # make sure can register multiple users with no username
    # Note that current WTForms (2.2.1) has a bug where StringFields can never be
    # None - it changes them to an empty string. DBs don't like that if you have
    # your column be 'nullable'.
    data = dict(email="u1@test.com", password="password")
    response = client.post(
        "/register", json=data, headers={"Content-Type": "application/json"}
    )
    assert response.status_code == 200
    logout(client)

    data = dict(email="u2@test.com", password="password")
    response = client.post(
        "/register", json=data, headers={"Content-Type": "application/json"}
    )
    assert response.status_code == 200


def test_email_normalization(app, client):
    # should be able to login either as LP.com or lp.com or canonical unicode form
    data = dict(
        email="Imnumber\N{OHM SIGN}@LP.com",
        password="battery staple",
        password_confirm="battery staple",
    )

    response = client.post("/register", data=data, follow_redirects=True)
    assert b"Home Page" in response.data
    logout(client)

    # Test user can login after registering
    response = authenticate(
        client, email="Imnumber\N{OHM SIGN}@lp.com", password="battery staple"
    )
    assert response.status_code == 302

    logout(client)
    # Test user can login after registering using original non-canonical email
    response = authenticate(
        client, email="Imnumber\N{OHM SIGN}@LP.com", password="battery staple"
    )
    assert response.status_code == 302

    logout(client)
    # Test user can login after registering using original non-canonical email
    response = authenticate(
        client,
        email="Imnumber\N{GREEK CAPITAL LETTER OMEGA}@LP.com",
        password="battery staple",
    )
    assert response.status_code == 302


def test_email_normalization_options(app, client, get_message):
    # verify can set options for email_validator
    data = dict(
        email="\N{BLACK SCISSORS}@LP.com",
        password="battery staple",
        password_confirm="battery staple",
    )

    response = client.post("/register", data=data, follow_redirects=True)
    assert b"Home Page" in response.data
    logout(client)

    # turn off allowing 'local' part unicode.
    app.config["SECURITY_EMAIL_VALIDATOR_ARGS"] = {"allow_smtputf8": False}
    data = dict(
        email="\N{WHITE SCISSORS}@LP.com",
        password="battery staple",
        password_confirm="battery staple",
    )

    response = client.post("/register", data=data, follow_redirects=True)
    assert response.status_code == 200
    assert get_message("INVALID_EMAIL_ADDRESS") in response.data


@pytest.mark.babel()
def test_form_error(app, client, get_message):
    # A few form validations use ValidatorMixin which provides a lazy string
    # Since CLI doesn't render_template it was seeing those lazy strings.
    # This test basically just illustrates all this.
    from babel.support import LazyProxy

    with app.test_request_context("/register"):
        rform = ConfirmRegisterForm()

        rform.validate()
        assert isinstance(rform.errors["email"][0], LazyProxy)
        assert str(rform.errors["email"][0]).encode("utf-8") == get_message(
            "EMAIL_NOT_PROVIDED"
        )

        # make sure rendered template has converted LocalProxy strings.
        rendered = app.security.render_template(
            app.config["SECURITY_REGISTER_USER_TEMPLATE"],
            register_user_form=rform,
        )
        assert get_message("EMAIL_NOT_PROVIDED") in rendered.encode("utf-8")


@pytest.mark.settings(username_enable=True)
@pytest.mark.unified_signin()
def test_username(app, clients, get_message):
    client = clients
    data = dict(
        email="dude@lp.com",
        username="dude",
        password="awesome sunset",
    )
    response = client.post(
        "/register", json=data, headers={"Content-Type": "application/json"}
    )
    assert response.headers["Content-Type"] == "application/json"
    assert response.status_code == 200
    logout(client)

    # login using historic - email field to hold a username - won't work since
    # it is an EmailField
    response = json_authenticate(client, email="dude", password="awesome sunset")
    assert response.status_code == 400
    assert (
        get_message("INVALID_EMAIL_ADDRESS", username="dude")
        == response.json["response"]["errors"][0].encode()
    )
    # login using username
    response = client.post(
        "/login", json=dict(username="dude", password="awesome sunset")
    )
    assert response.status_code == 200
    logout(client)

    # login with email
    response = client.post(
        "/login", json=dict(email="dude@lp.com", password="awesome sunset")
    )
    assert response.status_code == 200
    logout(client)

    response = client.post(
        "/login", json=dict(emails="dude", password="awesome sunset")
    )
    assert response.status_code == 400
    assert (
        get_message("USER_DOES_NOT_EXIST")
        == response.json["response"]["field_errors"][""][0].encode()
    )

    # login using us-signin
    response = client.post(
        "/us-signin",
        data=dict(identity="dude", passcode="awesome sunset"),
        follow_redirects=True,
    )
    assert b"Welcome dude@lp.com" in response.data

    # make sure username is unique
    logout(client)
    data = dict(
        email="dude@lp.com",
        username="dude",
        password="awesome sunset",
    )
    response = client.post(
        "/register", json=data, headers={"Content-Type": "application/json"}
    )
    assert response.status_code == 400
    assert (
        get_message("USERNAME_ALREADY_ASSOCIATED", username="dude")
        == response.json["response"]["field_errors"]["username"][0].encode()
    )


@pytest.mark.settings(username_enable=True)
def test_username_template(app, client):
    # verify template displays username option
    response = client.get("/register")
    username_field = get_form_input_value(response, "username")
    assert username_field is not None


@pytest.mark.settings(username_enable=True)
@pytest.mark.unified_signin()
def test_username_normalize(app, client, get_message):
    data = dict(
        email="dude@lp.com",
        username="Imnumber\N{ROMAN NUMERAL ONE}",
        password="awesome sunset",
    )
    response = client.post(
        "/register", json=data, headers={"Content-Type": "application/json"}
    )
    assert response.status_code == 200
    logout(client)

    response = client.post(
        "/us-signin",
        data=dict(
            identity="Imnumber\N{LATIN CAPITAL LETTER I}", passcode="awesome sunset"
        ),
        follow_redirects=True,
    )
    assert b"Welcome dude@lp.com" in response.data


@pytest.mark.settings(username_enable=True, username_required=True)
def test_username_errors(app, client, get_message):
    data = dict(
        email="dude@lp.com",
        username="dud",
        password="awesome sunset",
    )
    response = client.post(
        "/register", json=data, headers={"Content-Type": "application/json"}
    )
    assert response.status_code == 400
    assert "Username must be at least" in response.json["response"]["errors"][0]

    data["username"] = "howlongcanIbebeforeyoucomplainIsupposereallyreallylong"
    response = client.post(
        "/register", json=data, headers={"Content-Type": "application/json"}
    )
    assert response.status_code == 400
    assert "Username must be at least" in response.json["response"]["errors"][0]

    # try evil characters
    data["username"] = "hi <script>doing evil</script>"
    response = client.post(
        "/register", json=data, headers={"Content-Type": "application/json"}
    )
    assert response.status_code == 400
    assert (
        get_message("USERNAME_ILLEGAL_CHARACTERS")
        == response.json["response"]["field_errors"]["username"][0].encode()
    )

    # No spaces or punctuation
    data["username"] = "hi there?"
    response = client.post(
        "/register", json=data, headers={"Content-Type": "application/json"}
    )
    assert response.status_code == 400
    assert (
        get_message("USERNAME_DISALLOWED_CHARACTERS")
        in response.json["response"]["errors"][0].encode()
    )

    data["username"] = None
    response = client.post(
        "/register", json=data, headers={"Content-Type": "application/json"}
    )
    assert response.status_code == 400
    assert (
        get_message("USERNAME_NOT_PROVIDED")
        == response.json["response"]["errors"][0].encode()
    )


def test_username_not_enabled(app, client, get_message):
    response = client.get("/register")
    assert b"username" not in response.data
    assert not hasattr(RegisterForm, "username")


@pytest.mark.filterwarnings(
    "ignore:.*The RegisterForm is deprecated.*:DeprecationWarning"
)
def test_legacy_style_login(app, sqlalchemy_datastore, get_message):
    # Show how to setup LoginForm to mimic legacy behavior of
    # allowing any identity in the email field.
    # N.B. for simplicity we don't enable confirmable....
    from flask_security import (
        RegisterForm,
        LoginForm,
        Security,
        uia_username_mapper,
        unique_identity_attribute,
    )
    from flask_security.utils import lookup_identity
    from werkzeug.local import LocalProxy
    from wtforms import StringField, ValidationError, validators

    def username_validator(form, field):
        # Side-effect - field.data is updated to normalized value.
        # Use proxy to we can declare this prior to initializing Security.
        _security = LocalProxy(lambda: app.extensions["security"])
        msg, field.data = _security.username_util.validate(field.data)
        if msg:
            raise ValidationError(msg)

    class MyRegisterForm(RegisterForm):
        # Note that unique_identity_attribute uses the defined field 'mapper' to
        # normalize. We validate before that to give better error messages and
        # to set the normalized value into the form for saving.
        username = StringField(
            "Username",
            validators=[
                validators.data_required(),
                username_validator,
                unique_identity_attribute,
            ],
        )

    class MyLoginForm(LoginForm):
        email = StringField("email", [validators.data_required()])

        def validate(self, **kwargs):
            self.user = lookup_identity(self.email.data)
            self.ifield = self.email
            if not super().validate(**kwargs):
                return False
            return True

    app.config["SECURITY_USER_IDENTITY_ATTRIBUTES"] = [
        {"username": {"mapper": uia_username_mapper}}
    ]
    security = Security(
        datastore=sqlalchemy_datastore,
        register_form=MyRegisterForm,
        login_form=MyLoginForm,
    )
    security.init_app(app)

    client = app.test_client()

    data = dict(
        email="mary2@lp.com",
        username="mary",
        password="awesome sunset",
        password_confirm="awesome sunset",
    )
    response = client.post("/register", data=data, follow_redirects=True)
    assert b"Welcome mary" in response.data
    logout(client)

    # log in with username
    response = client.post(
        "/login",
        data=dict(email="mary", password="awesome sunset"),
        follow_redirects=True,
    )
    # verify actually logged in
    response = client.get("/profile", follow_redirects=False)
    assert response.status_code == 200


@pytest.mark.confirmable()
@pytest.mark.settings(return_generic_responses=True, username_enable=True)
def test_generic_response(app, client, get_message):
    # Register should not expose whether email/username is already in system.
    recorded = []

    @user_not_registered.connect_via(app)
    def on_user_not_registered(app, **kwargs):
        recorded.append(kwargs)

    # register new user
    data = dict(
        email="dude@lp.com",
        username="dude",
        password="awesome sunset",
    )
    response = client.post("/register", json=data)
    assert response.status_code == 200
    assert len(app.mail.outbox) == 1
    assert len(recorded) == 0

    # try again - should not get ANY error - but should get an email
    response = client.post("/register", json=data)
    assert response.status_code == 200
    assert not any(
        e in response.json["response"].keys() for e in ["errors", "field_errors"]
    )
    # this is using the test template
    matcher = re.findall(r"\w+:.*", app.mail.outbox[1].body, re.IGNORECASE)
    kv = {m.split(":")[0]: m.split(":", 1)[1] for m in matcher}
    assert kv["User"] == "dude"
    assert kv["Email"] == "dude@lp.com"
    assert kv["RegisterBlueprint"] == "True"
    assert "/confirm" in kv["ConfirmationLink"]
    assert kv["ConfirmationToken"]
    assert not kv["ResetLink"]
    assert not kv["ResetToken"]

    # verify that signal sent.
    assert len(recorded) == 1
    nr = recorded[0]
    assert nr["existing_email"]
    assert nr["user"].email == "dude@lp.com"
    assert nr["form_data"]["email"] == "dude@lp.com"

    # Forms should get generic response - even though email already registered.
    response = client.post("/register", data=data, follow_redirects=True)
    assert get_message("CONFIRM_REGISTRATION", email="dude@lp.com") in response.data
    assert len(app.mail.outbox) == 3
    assert len(recorded) == 2

    # Try same email with different username
    response = client.post(
        "/register",
        data=dict(email="dude@lp.com", username="dude2", password="awesome sunset"),
        follow_redirects=True,
    )
    assert get_message("CONFIRM_REGISTRATION", email="dude@lp.com") in response.data
    assert len(app.mail.outbox) == 4
    assert len(recorded) == 3
    matcher = re.findall(r"\w+:.*", app.mail.outbox[3].body, re.IGNORECASE)
    kv = {m.split(":")[0]: m.split(":", 1)[1] for m in matcher}
    assert kv["User"] == "dude"


@pytest.mark.confirmable()
@pytest.mark.settings(return_generic_responses=True, username_enable=True)
def test_gr_existing_username(app, client, get_message):
    # Test a new email with an existing username
    # Should still return errors such as illegal password
    recorded = []

    @user_not_registered.connect_via(app)
    def on_user_not_registered(app, **kwargs):
        recorded.append(kwargs)

    client.post(
        "/register",
        json=dict(email="dude@lp.com", username="dude", password="awesome sunset"),
    )
    response = client.post(
        "/register",
        data=dict(email="dude39@lp.com", username="dude", password="awesome sunset"),
        follow_redirects=True,
    )
    assert get_message("CONFIRM_REGISTRATION", email="dude39@lp.com") in response.data
    assert len(app.mail.outbox) == 2
    assert len(recorded) == 1
    gr = app.mail.outbox[1]
    assert 'You attempted to register with a username "dude" that' in gr.body
    # test that signal sent.
    nr = recorded[0]
    assert not nr["existing_email"]
    assert not nr["user"]
    assert nr["existing_username"]
    assert nr["form_data"]["username"] == "dude"

    # should still get detailed errors about e.g. bad password
    data = dict(
        email="dude@lp.com",
        username="dude",
        password="a",
    )
    response = client.post("/register", json=data)
    assert response.status_code == 400
    assert response.json["response"]["errors"][0].encode() == get_message(
        "PASSWORD_INVALID_LENGTH", length=8
    )
    data = dict(
        email="dude@lp.com",
        username="dd",
        password="awesome sunset",
    )
    response = client.post("/register", json=data)
    assert response.status_code == 400
    assert response.json["response"]["errors"][0].encode() == get_message(
        "USERNAME_INVALID_LENGTH", min=4, max=32
    )


@pytest.mark.recoverable()
@pytest.mark.confirmable()
@pytest.mark.settings(
    return_generic_responses=True,
    username_enable=True,
    send_register_email_welcome_existing_template="welcome_existing",
)
def test_gr_extras(app, client, get_message):
    # If user tries to re-register - response email should contain reset password
    # link and (if applicable) a confirmation link
    data = dict(
        email="dude@lp.com",
        username="dude",
        password="awesome sunset",
    )
    response = client.post("/register", json=data)
    assert response.status_code == 200
    assert len(app.mail.outbox) == 1

    # now same email - same or different username
    data = dict(
        email="dude@lp.com",
        username="dude2",
        password="awesome sunset",
    )
    response = client.post("/register", json=data)
    assert response.status_code == 200
    assert len(app.mail.outbox) == 2
    matcher = re.findall(r"\w+:.*", app.mail.outbox[1].body, re.IGNORECASE)
    kv = {m.split(":")[0]: m.split(":", 1)[1] for m in matcher}
    assert kv["User"] == "dude"
    confirm_link = kv["ConfirmationLink"]
    response = client.get(confirm_link)
    assert response.status_code == 302

    # now confirmed - should not get confirmation link
    response = client.post("/register", json=data)
    assert response.status_code == 200
    assert len(app.mail.outbox) == 3
    matcher = re.findall(r"\w+:.*", app.mail.outbox[2].body, re.IGNORECASE)
    kv = {m.split(":")[0]: m.split(":", 1)[1] for m in matcher}
    assert not kv["ConfirmationLink"]
    assert not kv["ConfirmationToken"]

    # but should still have reset link - test that
    reset_link = kv["ResetLink"]
    response = client.post(
        reset_link,
        json=dict(password="awesome password2", password_confirm="awesome password2"),
    )
    assert response.status_code == 200

    response = client.post(
        "/login", json=dict(username="dude", password="awesome password2")
    )
    assert response.status_code == 200


@pytest.mark.recoverable()
@pytest.mark.confirmable()
@pytest.mark.settings(return_generic_responses=True)
def test_gr_real_html_template(app, client, get_message):
    # We have a test .txt template - but this will use the normal/real HTML template
    data = dict(
        email="dude@lp.com",
        password="awesome sunset",
    )
    response = client.post("/register", json=data)
    assert response.status_code == 200
    assert len(app.mail.outbox) == 1

    # now same email - same or different username
    data = dict(
        email="dude@lp.com",
        password="awesome sunset",
    )
    response = client.post("/register", json=data)
    assert response.status_code == 200
    assert len(app.mail.outbox) == 2
    matcher = re.findall(
        r'href="(\S*)"',
        app.mail.outbox[1].alternatives[0][0],
        re.IGNORECASE,
    )
    assert "/reset" in matcher[0]
    assert "/confirm" in matcher[1]


def test_subclass(app, sqlalchemy_datastore):
    # Test/show how to use multiple inheritance to override individual form fields.
    from wtforms import PasswordField, ValidationError
    from wtforms.validators import DataRequired
    from flask_security.forms import get_form_field_label

    def password_validator(form, field):
        if field.data.startswith("PASS"):
            raise ValidationError("Really - don't start a password with PASS")

    class NewPasswordFormMixinEx:
        password = PasswordField(
            get_form_field_label("password"),
            validators=[
                DataRequired(message="PASSWORD_NOT_PROVIDED"),
                password_validator,
            ],
        )

    class MyRegisterForm(NewPasswordFormMixinEx, RegisterFormV2):
        pass

    app.config["SECURITY_REGISTER_FORM"] = MyRegisterForm
    security = Security(datastore=sqlalchemy_datastore)
    security.init_app(app)

    client = app.test_client()

    data = dict(
        email="dude@lp.com",
        password="PASSmattmatt",
        password_confirm="PASSmattmatt",
    )
    response = client.post(
        "/register", json=data, headers={"Content-Type": "application/json"}
    )
    assert response.status_code == 400
    assert "Really - don't start" in response.json["response"]["errors"][0]


@pytest.mark.confirmable()
@pytest.mark.settings(return_generic_responses=True)
def test_my_mail_util(app, sqlalchemy_datastore):
    # Test that with generic_responses - we still can get syntax/validation errors.
    from flask_security import MailUtil, EmailValidateException

    class MyMailUtil(MailUtil):
        def validate(self, email):
            if email.startswith("mike"):
                raise EmailValidateException("No mikes allowed")

    init_app_with_options(
        app, sqlalchemy_datastore, **{"security_args": {"mail_util_cls": MyMailUtil}}
    )

    data = dict(
        email="mike@lp.com",
        password="awesome sunset",
    )
    client = app.test_client()
    response = client.post("/register", data=data)
    assert b"No mikes allowed" in response.data


@pytest.mark.settings(
    register_form=RegisterFormV2,
    post_register_view="/post_register",
)
def test_regv2(app, client, get_message):
    # default config should require password, password_confirm and not allow username
    response = client.get("/register")
    assert b"<h1>Register</h1>" in response.data
    email = get_form_input(response, "email")
    assert all(s in email for s in ["required", 'type="email"'])
    pw = get_form_input(response, "password")
    assert all(s in pw for s in ["required", 'type="password"'])
    pwc = get_form_input(response, "password_confirm")
    assert all(s in pwc for s in ["required", 'type="password"'])

    assert not get_form_input(response, "username")

    # check password required
    data = dict(
        email="dude@lp.com",
        password="",
        password_confirm="battery staple",
        next="",
    )
    response = client.post("/register", data=data, follow_redirects=True)
    assert get_message("PASSWORD_NOT_PROVIDED") in response.data

    # check confirm required
    data = dict(
        email="dude@lp.com",
        password="battery staple",
        password_confirm="",
        next="",
    )
    response = client.post("/register", data=data, follow_redirects=True)
    assert get_message("PASSWORD_NOT_PROVIDED") in response.data

    # JSON also required password_confirm in V2
    response = client.post("/register", json=data)
    assert (
        get_message("PASSWORD_NOT_PROVIDED")
        == response.json["response"]["errors"][0].encode()
    )

    # check confirm matches
    data = dict(
        email="dude@lp.com",
        password="battery staple",
        password_confirm="batery staple",
        next="",
    )
    response = client.post("/register", data=data, follow_redirects=True)
    assert get_message("RETYPE_PASSWORD_MISMATCH") in response.data

    data = dict(
        email="dude@lp.com",
        password="battery staple",
        password_confirm="battery staple",
        next="",
    )
    response = client.post("/register", data=data, follow_redirects=True)
    assert b"Post Register" in response.data


@pytest.mark.settings(
    register_form=RegisterFormV2,
    post_register_view="/post_register",
    password_confirm_required=False,
)
def test_regv2_no_confirm(app, client, get_message):
    # Test password confirm not required
    response = client.get("/register")
    assert b"<h1>Register</h1>" in response.data
    email = get_form_input(response, "email")
    assert all(s in email for s in ["required", 'type="email"'])
    pw = get_form_input(response, "password")
    assert all(s in pw for s in ["required", 'type="password"'])

    assert not get_form_input(response, "password_confirm")
    assert not get_form_input(response, "username")

    data = dict(
        email="dude@lp.com",
        password="abc",
    )
    response = client.post("/register", data=data, follow_redirects=True)
    assert get_message("PASSWORD_INVALID_LENGTH", length=8) in response.data

    data = dict(
        email="dude@lp.com",
        password="battery staple",
        password_confirm="battery terminal",  # Ignored
        next="/my_next_idea",
    )
    response = client.post("/register", data=data, follow_redirects=False)
    assert response.location == "/my_next_idea"


@pytest.mark.settings(
    use_register_v2=True,
    post_register_view="/post_register",
    password_confirm_required=False,
    username_enable=True,
    username_required=True,
)
def test_regv2_no_confirm_username(app, client, get_message):
    # Test password confirm not required but username is
    response = client.get("/register")
    assert b"<h1>Register</h1>" in response.data
    email = get_form_input(response, "email")
    assert all(s in email for s in ["required", 'type="email"'])
    pw = get_form_input(response, "password")
    assert all(s in pw for s in ["required", 'type="password"'])

    assert not get_form_input(response, "password_confirm")

    us = get_form_input(response, "username")
    assert all(s in us for s in ["required", 'type="text"'])

    data = dict(
        email="dude@lp.com",
        password="battery staple",
    )
    response = client.post("/register", data=data, follow_redirects=True)
    assert get_message("USERNAME_NOT_PROVIDED") in response.data

    data = dict(
        email="dude@lp.com",
        password="battery staple",
        username="dude",
    )
    response = client.post("/register", data=data, follow_redirects=True)
    assert b"Post Register" in response.data


@pytest.mark.settings(
    use_register_v2=True,
    password_confirm_required=False,
)
def test_subclass_v2(app, sqlalchemy_datastore):
    # Test that is create our own RegisterForm the USE_REGISTER_V2 config is ignored
    class MyRegisterForm(RegisterFormV2):
        from wtforms.validators import Length

        myfield = StringField(label="My field", validators=[Length(min=8)])

    app.config["SECURITY_REGISTER_FORM"] = MyRegisterForm
    security = Security(datastore=sqlalchemy_datastore)
    security.init_app(app)

    client = app.test_client()
    data = dict(
        email="dude@lp.com",
        password="battery staple",
        myfield="short",
    )
    response = client.post("/register", json=data)
    assert (
        response.json["response"]["errors"][0]
        == "Field must be at least 8 characters long."
    )


@pytest.mark.unified_signin()
@pytest.mark.confirmable()
@pytest.mark.settings(password_required=False, use_register_v2=True)
def test_allow_null_password_v2(client, get_message):
    # Test password not required with new RegisterFormV2
    response = client.get("/register")
    data = dict(email="trp@lp.com")
    pw = get_form_input(response, "password")
    assert "required" not in pw
    pwc = get_form_input(response, "password_confirm")
    assert "required" not in pwc

    response = client.post("/register", data=data, follow_redirects=True)
    assert get_message("CONFIRM_REGISTRATION", email="trp@lp.com") in response.data
    logout(client)

    # should be able to register with password and password_confirm
    data = dict(email="trp2@lp.com", password="battery staple")
    response = client.post("/register", data=data, follow_redirects=True)
    assert get_message("RETYPE_PASSWORD_MISMATCH") in response.data

    data = dict(
        email="trp2@lp.com",
        password="battery staple",
        password_confirm="battery staple",
    )
    response = client.post("/register", data=data, follow_redirects=True)
    assert get_message("CONFIRM_REGISTRATION", email="trp2@lp.com") in response.data
