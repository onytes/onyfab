
Deployment tools for Django projects based on Fabric
====================================================

Fabric only works on Python 2, so ensure your virtualenv uses it.

.. code-block:: bash

    # specify python path
    $ virtualenv -p /usr/bin/python2 venv

Add to your virtualenv:
 * fabric
 * jinja2

.. code-block:: bash

    $ source venv/bin/activate
    $ pip install -r requirements.txt



Configuration File
------------------

Write on it your configuration. Check the template on `conf.py.template <conf.py.template>`_ change it and rename it to ``conf.py``.

If you want to add it to your control version, you can specify the conf file path to ``onyfab`` through a env variable.

.. code-block:: bash

    export ONYFAB_CONF_PATH="../config/fab-conf.py"



Disclaimer:
-----------
I'm new to deployment and maybe something could be wrong or doesn't fit with best practices. Your comments and suggestions are welcome.

Contact:

* `@pvieytes`_
* `www.pablovieytes.com`_


.. _@pvieytes: https://github.com/pvieytes
.. _www.pablovieytes.com: http://www.pablovieytes.com
