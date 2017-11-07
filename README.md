# appconfig

Scripted deployment of dlce webapps


## Deploying an app

### Deploying new code

All new code must be pushed to the `app` repository on GitHub.
While no local installation of the app or a local database are required, it is recommended to run the app's tests
before deployment.

1. Activate the "remote control":
```
$ workon appconfig
```

2. Change into the config directory for the app:
```
$ cd appconfig/<app>
```

3. Run the `deploy` task, passing `test` or `production` as deployment mode and optionally a custom 
host using `fab`'s `-H` option, e.g.
```
$ fab -H vbox deploy:production
```
Answer all questions regarding the database in the negative.


### Deploying new data

New data can be deployed in two ways, either via alembic migrations, altering an existing database, or by replacing
the database wholesale.
In the first case, the migration must be pushed to the app's repository on GitHub.

