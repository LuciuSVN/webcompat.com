#!/usr/bin/env python
# -*- coding: utf-8 -*-
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.

import os
import time
import urllib
from datetime import datetime
from flask import (flash, g, redirect, request, render_template, session,
                   url_for, abort)
from flask.ext.github import GitHubError
from form import (build_formdata, get_browser_name, get_browser_version,
                  IssueForm, AUTH_REPORT, PROXY_REPORT)
from issues import report_issue, proxy_report_issue
from models import db_session, User
from webcompat import github, app


@app.teardown_appcontext
def shutdown_session(exception=None):
    db_session.remove()


@app.before_request
def before_request():
    g.user = None
    if 'user_id' in session:
        g.user = User.query.get(session['user_id'])


@app.after_request
def after_request(response):
    db_session.remove()
    return response


@github.access_token_getter
def token_getter():
    user = g.user
    if user is not None:
        return user.github_access_token


@app.route('/login')
def login():
    if session.get('user_id', None) is None:
        return github.authorize('public_repo')
    else:
        return u'Already logged in'


# OAuth2 callback handler that GitHub requires.
# If this moves, it needs to change in GitHub settings as well
@app.route('/callback')
@github.authorized_handler
def authorized(access_token):
    if access_token is None:
        flash(u'Something went wrong trying to sign into GitHub. :(', 'error')
        return redirect(url_for('index'))
    user = User.query.filter_by(github_access_token=access_token).first()
    if user is None:
        user = User(access_token)
        db_session.add(user)
    user.github_access_token = access_token
    db_session.commit()

    session['user_id'] = user.id
    return redirect(url_for('file_issue'))


@app.route('/logout')
def logout():
    session.pop('user_id', None)
    session.pop('form_data', None)
    flash(u'You were successfully logged out.', 'info')
    return redirect(url_for('index'))


# This route won't ever be viewed by a human being--there's not
# a corresponding template. It exists just to submit an issue after
# a user auths with GitHub.
@app.route('/file')
def file_issue():
    '''File an issue on behalf of the user that just gave us authorization.'''
    response = report_issue(session['form_data'])
    # Get rid of stashed form data
    session.pop('form_data', None)
    return redirect(url_for('thanks', number=response.get('number')))


@app.route('/issues')
def show_issues():
    return redirect(url_for('new_issue'), code=307)


@app.route('/', methods=['GET', 'POST'])
def new_issue():
    '''Main view where people come to report issues.'''
    form = IssueForm(request.form)
    # add browser and version to form object data
    form.browser.data = get_browser_name(request.headers.get('User-Agent'))
    form.version.data = get_browser_version(request.headers.get('User-Agent'))
    # GET means you want to file a report.
    if request.method == 'GET':
        return render_template('index.html', form=form)
    # Form submission.
    elif request.method == 'POST' and form.validate():
        if request.form.get('submit-type') == AUTH_REPORT:
            if g.user:  # If you're already authed, submit the bug.
                response = report_issue(request.form)
                return redirect(url_for('thanks',
                                number=response.get('number')))
            else:  # Stash form data into session, go do GitHub auth
                session['form_data'] = request.form
                return redirect(url_for('login'))
        elif request.form.get('submit-type') == PROXY_REPORT:
            # `response` here is a Requests Response object, because
            # the proxy_report_issue crafts a manual request with Requests
            response = proxy_report_issue(request.form)
            return redirect(url_for('thanks',
                            number=response.json().get('number')))
    else:
        # Validation failed, re-render the form with the errors.
        return render_template('index.html', form=form)


@app.route('/issues/<number>')
def show_issue(number):
    # In the future we can display the issue on our site, but for now
    # we're just going to 307 to github issues.
    uri = u"https://github.com/{0}/{1}".format(app.config['ISSUES_REPO_URI'],
                                               number)
    return redirect(uri, code=307)


@app.route('/thanks/<number>')
def thanks(number):
    if number.isdigit():
        issue = number
        uri = u"https://github.com/{0}/{1}".format(
            app.config['ISSUES_REPO_URI'], number)
        text = u"I just filed a bug on the internet: "
        encoded_issue = urllib.quote(uri.encode("utf-8"))
        encoded_text = urllib.quote(text.encode("utf-8"))
    else:
        abort(404)
    return render_template('thanks.html', number=issue,
                           encoded_issue=encoded_issue,
                           encoded_text=encoded_text)


@app.route('/about')
def about():
    return render_template('about.html')


@app.errorhandler(GitHubError)
def jumpship(e):
    print(e)
    session.pop('user_id', None)
    flash('Something bad happened. Please try again?', 'error')
    return redirect(url_for('index'))


@app.errorhandler(404)
def not_found(err):
    message = "We can't find what you are looking for."
    return render_template('error.html',
                           error_code=404,
                           error_message=message), 404


@app.errorhandler(500)
def not_found(err):
    message = "Internal Server Error"
    return render_template('error.html',
                           error_code=500,
                           error_message=message), 500
