import hashlib
import pickle
import pytest
import time
import zlib

from copy import deepcopy
from datetime import datetime
from urllib.parse import quote

from django.conf import settings
from django.core.cache import caches
from django.core.cache.utils import make_template_fragment_key
from django.template import base as template
from django.template.context import Context
from django.test import override_settings
from django.utils.encoding import force_bytes
from django.utils.safestring import SafeText

from adv_cache_tag.tag import CacheTag


class TestTag:
    """First basic test case to be able to test python/django compatibility."""

    @classmethod
    def reload_config(cls):
        """Resest the ``CacheTag`` configuration from current settings"""
        CacheTag.options.versioning = getattr(settings, "ADV_CACHE_VERSIONING", False)
        CacheTag.options.compress = getattr(settings, "ADV_CACHE_COMPRESS", False)
        CacheTag.options.compress_level = getattr(settings, "ADV_CACHE_COMPRESS_LEVEL", False)
        CacheTag.options.compress_spaces = getattr(settings, "ADV_CACHE_COMPRESS_SPACES", False)
        CacheTag.options.include_pk = getattr(settings, "ADV_CACHE_INCLUDE_PK", False)
        CacheTag.options.cache_backend = getattr(settings, "ADV_CACHE_BACKEND", "default")
        CacheTag.options.resolve_fragment = getattr(settings, "ADV_CACHE_RESOLVE_NAME", False)

        # generate a token for this site, based on the secret_key
        CacheTag.RAW_TOKEN = (
            "RAW_"
            + hashlib.sha1(
                b"RAW_TOKEN_SALT1"
                + force_bytes(
                    hashlib.sha1(b"RAW_TOKEN_SALT2" + force_bytes(settings.SECRET_KEY)).hexdigest()
                )
            ).hexdigest()
        )

        # tokens to use around the already parsed parts of the cached template
        CacheTag.RAW_TOKEN_START = (
            template.BLOCK_TAG_START + CacheTag.RAW_TOKEN + template.BLOCK_TAG_END
        )
        CacheTag.RAW_TOKEN_END = (
            template.BLOCK_TAG_START + "end" + CacheTag.RAW_TOKEN + template.BLOCK_TAG_END
        )

    def setup_method(self):
        """Clean stuff and create an object to use in templates, and some counters."""
        # Clear the cache
        for cache_name in settings.CACHES:
            caches[cache_name].clear()

        # Reset CacheTag config with default value (from the ``override_settings``)
        self.reload_config()

        # And an object to cache in template
        self.obj = {
            "pk": 42,
            "name": "foobar",
            "get_name": self.get_name,
            "get_foo": self.get_foo,
            "updated_at": datetime(2015, 10, 27, 0, 0, 0),
        }

        # To count the number of calls of ``get_name`` and ``get_foo``.
        self.get_name_called = 0
        self.get_foo_called = 0

    def get_name(self):
        """Called in template when asking for ``obj.get_name``."""
        self.get_name_called += 1
        return self.obj["name"]

    def get_foo(self):
        """Called in template when asking for ``obj.get_foo``."""
        self.get_foo_called += 1
        return "foo %d" % self.get_foo_called

    def teardown_method(self):
        """Clear caches at the end."""

        for cache_name in settings.CACHES:
            caches[cache_name].clear()

    @classmethod
    def teardown_class(cls):
        """At the very end of all theses tests, we reload the CacheTag config."""

        # Reset CacheTag config after the end of ``override_settings``
        cls.reload_config()

    @staticmethod
    def get_template_key(fragment_name, vary_on=None, prefix="template.cache"):
        """Compose the cache key of a template."""
        if vary_on is None:
            vary_on = ()
        key = ":".join([quote(force_bytes(var)) for var in vary_on])
        args = hashlib.md5(force_bytes(key))
        return (prefix + ".%s.%s") % (fragment_name, args.hexdigest())

    def render(self, template_text, extend_context_dict=None):
        """Utils to render a template text with a context given as a dict."""
        context_dict = {"obj": self.obj}
        if extend_context_dict:
            context_dict.update(extend_context_dict)
        return template.Template(template_text).render(Context(context_dict))

    def test_default_cache(self):
        """This test is only to validate the testing procedure."""

        expected = "foobar"

        t = """
            {% load cache %}
            {% cache 1 test_cached_template obj.pk obj.updated_at %}
                {{ obj.get_name }}
            {% endcache %}
        """

        # Render a first time, should miss the cache
        assert self.render(t).strip() == expected
        assert self.get_name_called == 1

        # Now the rendered template should be in cache
        key = make_template_fragment_key(
            "test_cached_template", vary_on=[self.obj["pk"], self.obj["updated_at"]]
        )
        assert key == "template.cache.test_cached_template.27ec3d708052c29b29e013c11f4cd8d0"

        assert caches["default"].get(key).strip() == expected

        # Render a second time, should hit the cache
        assert self.render(t).strip() == expected
        assert self.get_name_called == 1  # Still 1

    def test_adv_cache(self):
        """Test default behaviour with default settings."""

        expected = "foobar"

        t = """
            {% load adv_cache %}
            {% cache 1 test_cached_template obj.pk obj.updated_at %}
                {{ obj.get_name }}
            {% endcache %}
        """

        # Render a first time, should miss the cache
        assert self.render(t).strip() == expected
        assert self.get_name_called == 1

        # Now the rendered template should be in cache
        key = self.get_template_key(
            "test_cached_template", vary_on=[self.obj["pk"], self.obj["updated_at"]]
        )
        assert key == "template.cache.test_cached_template.0cac9a03d5330dd78ddc9a0c16f01403"

        # But it should NOT be the exact content as adv_cache_tag adds a version
        assert caches["default"].get(key).strip() != expected

        # It should be the version from `adv_cache_tag`
        cache_expected = b"1::\n                foobar"
        assert caches["default"].get(key).strip() == cache_expected

        # Render a second time, should hit the cache
        assert self.render(t).strip() == expected
        assert self.get_name_called == 1  # Still 1

    def test_timeout_value(self):
        "Test that timeout value is ``None`` or an integer." ""

        ok_values = ("0", "1", "9999", '"0"', '"1"', '"9999"', "None")
        ko_values = ("-1", "-9999", '"-1"', '"-9999"', '"foo"', '""', "12.3", '"12.3"')

        t = """
            {%% load adv_cache %%}
            {%% cache %s test_cached_template obj.pk obj.updated_at %%}
                {{ obj.get_name }}
            {%% endcache %%}
        """

        for value in ok_values:

            def test_value(value):
                self.render(t % value)

            if hasattr(self, "subTest"):
                with self.subTest(value=value):
                    test_value(value)
            else:
                test_value(value)

        for value in ko_values:

            def test_value(value):
                with pytest.raises(template.TemplateSyntaxError) as raise_context:
                    self.render(t % value)
                assert "tag got a non-integer (or None) timeout value" in str(raise_context)

            if hasattr(self, "subTest"):
                with self.subTest(value=value):
                    test_value(value)
            else:
                test_value(value)

    def test_quoted_fragment_name(self):
        """Test quotes behaviour around the fragment name."""

        t = """
            {% load adv_cache %}
            {% cache 1 "test_cached_template obj.pk obj.updated_at %}
                {{ obj.get_name }}
            {% endcache %}
        """

        with pytest.raises(ValueError) as raise_context:
            self.render(t)
        assert "incoherent" in str(raise_context)

        t = """
            {% load adv_cache %}
            {% cache 1 test_cached_template" obj.pk obj.updated_at %}
                {{ obj.get_name }}
            {% endcache %}
        """

        with pytest.raises(ValueError) as raise_context:
            self.render(t)
        assert "incoherent" in str(raise_context)

        t = """
            {% load adv_cache %}
            {% cache 1 'test_cached_template obj.pk obj.updated_at %}
                {{ obj.get_name }}
            {% endcache %}
        """

        with pytest.raises(ValueError) as raise_context:
            self.render(t)
        assert "incoherent" in str(raise_context)

        t = """
            {% load adv_cache %}
            {% cache 1 test_cached_template" obj.pk obj.updated_at %}
                {{ obj.get_name }}
            {% endcache %}
        """

        with pytest.raises(ValueError) as raise_context:
            self.render(t)
        assert "incoherent" in str(raise_context)

        t = """
            {% load adv_cache %}
            {% cache 1 "test_cached_template" obj.pk "foo" obj.updated_at %}
                {{ obj.get_name }} foo
            {% endcache %}
        """
        expected = "foobar foo"
        assert self.render(t).strip() == expected
        key = self.get_template_key(
            "test_cached_template",
            vary_on=[self.obj["pk"], "foo", self.obj["updated_at"]],
        )
        # no quotes arround `test_cached_template`
        assert key == "template.cache.test_cached_template.f2f294788f4c38512d3b544ce07befd0"
        cache_expected = b"1::\n                foobar foo"
        assert caches["default"].get(key).strip() == cache_expected

        t = """
            {% load adv_cache %}
            {% cache 1 'test_cached_template' obj.pk "bar" obj.updated_at %}
                {{ obj.get_name }} bar
            {% endcache %}
        """
        expected = "foobar bar"
        assert self.render(t).strip() == expected
        key = self.get_template_key(
            "test_cached_template",
            vary_on=[self.obj["pk"], "bar", self.obj["updated_at"]],
        )
        # no quotes arround `test_cached_template`
        assert key == "template.cache.test_cached_template.8bccdefc91dc857fc02f6938bf69b816"
        cache_expected = b"1::\n                foobar bar"
        assert caches["default"].get(key).strip() == cache_expected

    @override_settings(
        ADV_CACHE_VERSIONING=True,
    )
    def test_versioning(self):
        """Test with ``ADV_CACHE_VERSIONING`` set to ``True``."""

        # Reset CacheTag config with default value (from the ``override_settings``)
        self.reload_config()

        expected = "foobar"

        t = """
            {% load adv_cache %}
            {% cache 1 test_cached_template obj.pk obj.updated_at %}
                {{ obj.get_name }}
            {% endcache %}
        """

        # Render a first time, should miss the cache
        assert self.render(t).strip() == expected
        assert self.get_name_called == 1

        # Now the rendered template should be in cache

        # ``obj.updated_at`` is not in the key anymore, serving as the object version
        key = self.get_template_key("test_cached_template", vary_on=[self.obj["pk"]])
        assert key == "template.cache.test_cached_template.a1d0c6e83f027327d8461063f4ac58a6"

        # It should be in the cache, with the ``updated_at`` in the version
        cache_expected = b"1::2015-10-27 00:00:00::\n                foobar"
        assert caches["default"].get(key).strip() == cache_expected

        # Render a second time, should hit the cache
        assert self.render(t).strip() == expected
        assert self.get_name_called == 1  # Still 1

        # We can update the date
        self.obj["updated_at"] = datetime(2015, 10, 28, 0, 0, 0)

        # Render with the new date, we should miss the cache because of the new "version
        assert self.render(t).strip() == expected
        assert self.get_name_called == 2  # One more

        # It should be in the cache, with the new ``updated_at`` in the version
        cache_expected = b"1::2015-10-28 00:00:00::\n                foobar"
        assert caches["default"].get(key).strip() == cache_expected

        # Render a second time, should hit the cache
        assert self.render(t).strip() == expected
        assert self.get_name_called == 2  # Still 2

    @override_settings(
        ADV_CACHE_INCLUDE_PK=True,
    )
    def test_primary_key(self):
        """Test with ``ADV_CACHE_INCLUDE_PK`` set to ``True``."""

        # Reset CacheTag config with default value (from the ``override_settings``)
        self.reload_config()

        expected = "foobar"

        t = """
            {% load adv_cache %}
            {% cache 1 test_cached_template obj.pk obj.updated_at %}
                {{ obj.get_name }}
            {% endcache %}
        """

        # Render a first time, should miss the cache
        assert self.render(t).strip() == expected
        assert self.get_name_called == 1

        # Now the rendered template should be in cache

        # We add the pk as a part to the fragment name
        key = self.get_template_key(
            "test_cached_template.%s" % self.obj["pk"],
            vary_on=[self.obj["pk"], self.obj["updated_at"]],
        )
        assert key == "template.cache.test_cached_template.42.0cac9a03d5330dd78ddc9a0c16f01403"

        # It should be in the cache
        cache_expected = b"1::\n                foobar"
        assert caches["default"].get(key).strip() == cache_expected

        # Render a second time, should hit the cache
        assert self.render(t).strip() == expected
        assert self.get_name_called == 1  # Still 1

    @override_settings(
        ADV_CACHE_COMPRESS_SPACES=True,
    )
    def test_space_compression(self):
        """Test with ``ADV_CACHE_COMPRESS_SPACES`` set to ``True``."""

        # Reset CacheTag config with default value (from the ``override_settings``)
        self.reload_config()

        expected = "foobar"

        t = """
            {% load adv_cache %}
            {% cache 1 test_cached_template obj.pk obj.updated_at %}
                {{ obj.get_name }}
            {% endcache %}
        """

        # Render a first time, should miss the cache
        assert self.render(t).strip() == expected
        assert self.get_name_called == 1

        # Now the rendered template should be in cache
        key = self.get_template_key(
            "test_cached_template", vary_on=[self.obj["pk"], self.obj["updated_at"]]
        )
        assert key == "template.cache.test_cached_template.0cac9a03d5330dd78ddc9a0c16f01403"

        # It should be in the cache, with only one space instead of many white spaces
        cache_expected = b"1:: foobar "
        assert caches["default"].get(key) == cache_expected

        # Render a second time, should hit the cache
        assert self.render(t).strip() == expected
        assert self.get_name_called == 1  # Still 1

    @override_settings(
        ADV_CACHE_COMPRESS=True,
    )
    def test_compression(self):
        """Test with ``ADV_CACHE_COMPRESS`` set to ``True``."""

        # Reset CacheTag config with default value (from the ``override_settings``)
        self.reload_config()

        expected = "foobar"

        # We don't use new lines here because too complicated to set empty lines with only
        # spaces in a docstring with we'll have to compute the compressed version
        t = (
            "{% load adv_cache %}{% cache 1 test_cached_template obj.pk obj.updated_at %}"
            "  {{ obj.get_name }}  {% endcache %}"
        )

        # Render a first time, should miss the cache
        assert self.render(t).strip() == expected
        assert self.get_name_called == 1

        # Now the rendered template should be in cache
        key = self.get_template_key(
            "test_cached_template", vary_on=[self.obj["pk"], self.obj["updated_at"]]
        )
        assert key == "template.cache.test_cached_template.0cac9a03d5330dd78ddc9a0c16f01403"

        # It should be in the cache, compressed
        # We use ``SafeText`` as django does in templates
        compressed = zlib.compress(pickle.dumps(SafeText("  foobar  ")), -1)
        cache_expected = b"1::" + compressed
        assert caches["default"].get(key) == cache_expected

        # Render a second time, should hit the cache
        assert self.render(t).strip() == expected
        assert self.get_name_called == 1  # Still 1

        # Changing the compression level should not invalidate the cache
        CacheTag.options.compress_level = 9
        assert self.render(t).strip() == expected
        assert self.get_name_called == 1  # Still 1

        # But if the cache is invalidated, the new one will use this new level
        caches["default"].delete(key)
        assert self.render(t).strip() == expected
        assert self.get_name_called == 2  # One more
        compressed = zlib.compress(pickle.dumps(SafeText("  foobar  ")), 9)
        cache_expected = b"1::" + compressed
        assert caches["default"].get(key) == cache_expected

    @override_settings(
        ADV_CACHE_COMPRESS=True,
        ADV_CACHE_COMPRESS_SPACES=True,
    )
    def test_full_compression(self):
        """Test with ``ADV_CACHE_COMPRESS`` and ``ADV_CACHE_COMPRESS_SPACES`` set to ``True``."""

        # Reset CacheTag config with default value (from the ``override_settings``)
        self.reload_config()

        expected = "foobar"

        t = """
            {% load adv_cache %}
            {% cache 1 test_cached_template obj.pk obj.updated_at %}
                {{ obj.get_name }}
            {% endcache %}
        """

        # Render a first time, should miss the cache
        assert self.render(t).strip() == expected
        assert self.get_name_called == 1

        # Now the rendered template should be in cache
        key = self.get_template_key(
            "test_cached_template", vary_on=[self.obj["pk"], self.obj["updated_at"]]
        )
        assert key == "template.cache.test_cached_template.0cac9a03d5330dd78ddc9a0c16f01403"

        # It should be in the cache, compressed
        # We DON'T use ``SafeText`` as in ``test_compression`` because with was converted back
        # to a real string when removing spaces
        compressed = zlib.compress(pickle.dumps(" foobar "))
        cache_expected = b"1::" + compressed
        assert caches["default"].get(key) == cache_expected

        # Render a second time, should hit the cache
        assert self.render(t).strip() == expected
        assert self.get_name_called == 1  # Still 1

    @override_settings(
        ADV_CACHE_BACKEND="foo",
    )
    def test_cache_backend(self):
        """Test with ``ADV_CACHE_BACKEND`` to another value than ``default``."""

        # Reset CacheTag config with default value (from the ``override_settings``)
        self.reload_config()

        expected = "foobar"

        t = """
            {% load adv_cache %}
            {% cache 1 test_cached_template obj.pk obj.updated_at %}
                {{ obj.get_name }}
            {% endcache %}
        """

        # Render a first time, should miss the cache
        assert self.render(t).strip() == expected
        assert self.get_name_called == 1

        # Now the rendered template should be in cache
        key = self.get_template_key(
            "test_cached_template", vary_on=[self.obj["pk"], self.obj["updated_at"]]
        )
        assert key, "template.cache.test_cached_template.0cac9a03d5330dd78ddc9a0c16f01403"

        # It should be in the cache
        cache_expected = b"1::\n                foobar"

        # But not in the ``default`` cache
        assert caches["default"].get(key) is None

        # But in the ``foo`` cache
        assert caches["foo"].get(key).strip() == cache_expected

        # Render a second time, should hit the cache
        assert self.render(t).strip() == expected
        assert self.get_name_called == 1  # Still 1

    @override_settings(
        ADV_CACHE_COMPRESS_SPACES=True,
    )
    def test_partial_cache(self):
        """Test the ``nocache`` templatetag."""

        # Reset CacheTag config with default value (from the ``override_settings``)
        self.reload_config()

        expected = "foobar  foo 1  !!"

        t = """
            {% load adv_cache %}
            {% cache 1 test_cached_template obj.pk obj.updated_at %}
                {{ obj.get_name }}
                {% nocache %}
                    {{ obj.get_foo }}
                {% endnocache %}
                !!
            {% endcache %}
        """

        # Render a first time, should miss the cache
        assert self.render(t).strip() == expected
        assert self.get_name_called == 1
        assert self.get_foo_called == 1

        # Now the rendered template should be in cache
        key = self.get_template_key(
            "test_cached_template", vary_on=[self.obj["pk"], self.obj["updated_at"]]
        )
        assert key == "template.cache.test_cached_template.0cac9a03d5330dd78ddc9a0c16f01403"

        # It should be in the cache, with the RAW part
        cache_expected = (
            b"1:: foobar {%endRAW_38a11088962625eb8c913e791931e2bc2e3c7228%} "
            b"{{obj.get_foo}} {%RAW_38a11088962625eb8c913e791931e2bc2e3c7228%} !! "
        )
        assert caches["default"].get(key).strip() == cache_expected.strip()

        # Render a second time, should hit the cache but not for ``get_foo``
        expected = "foobar  foo 2  !!"
        assert self.render(t).strip() == expected
        assert self.get_name_called == 1  # Still 1
        assert self.get_foo_called == 2  # One more call to the non-cached part

    @override_settings(
        ADV_CACHE_VERSIONING=True,
    )
    def test_internal_version(self):
        """Test a cache with `Meta.internal_version` set."""

        # Reset CacheTag config with default value (from the ``override_settings``)
        self.reload_config()

        expected = "foobar"

        t = """
            {% load adv_cache_test %}
            {% cache_with_version 1 test_cache_with_version obj.pk %}
                {{ obj.get_name }}
            {% endcache_with_version %}
        """

        # Render a first time, should miss the cache
        assert self.render(t).strip() == expected
        assert self.get_name_called == 1

        # It should be in the cache, with the ``internal_version`` in the version
        key = "template.cache_with_version.test_cache_with_version.a1d0c6e83f027327d8461063f4ac58a6"
        cache_expected = b"1|v1::\n                foobar"
        assert caches["default"].get(key).strip() == cache_expected

        self.get_name_called = 0
        # Calling it a new time should hit the cache
        assert self.render(t).strip() == expected
        assert self.get_name_called == 0

        # Changing the interval version should miss the cache
        from .testproject.adv_cache_test_app.templatetags.adv_cache_test import (
            InternalVersionTag,
        )

        InternalVersionTag.options.internal_version = "v2"
        assert self.render(t).strip() == expected
        assert self.get_name_called == 1

        # It should be in the cache, with the new ``internal_version`` in the version
        key = "template.cache_with_version.test_cache_with_version.a1d0c6e83f027327d8461063f4ac58a6"
        cache_expected = b"1|v2::\n                foobar"
        assert caches["default"].get(key).strip() == cache_expected

    def test_new_class(self):
        """Test a new class based on ``CacheTag``."""

        expected = "foobar  foo 1  !!"

        t = """
            {% load adv_cache_test %}
            {% cache_test 1 multiplicator test_cached_template obj.pk obj.updated_at %}
                {{ obj.get_name }}
                {% nocache_test %}
                    {{ obj.get_foo }}
                {% endnocache_test %}
                !!
            {% endcache_test %}
        """

        # Render a first time, should miss the cache
        assert self.render(t, {"multiplicator": 10}).strip() == expected
        assert self.get_name_called == 1
        assert self.get_foo_called == 1

        # Now the rendered template should be in cache
        key = self.get_template_key(
            "test_cached_template",
            vary_on=[self.obj["pk"], self.obj["updated_at"]],
            prefix="template.cache_test",
        )
        assert key == "template.cache_test.test_cached_template.0cac9a03d5330dd78ddc9a0c16f01403"

        # It should be in the cache, with the RAW part
        cache_expected = (
            b"1:: foobar {%endRAW_38a11088962625eb8c913e791931e2bc2e3c7228%} "
            b"{{obj.get_foo}} {%RAW_38a11088962625eb8c913e791931e2bc2e3c7228%} !! "
        )
        assert caches["default"].get(key).strip() == cache_expected.strip()

        # We'll check that our multiplicator was really applied
        cache = caches["default"]
        expire_at = cache._expire_info[cache.make_key(key, version=None)]
        now = time.time()
        # In more that one second (default expiry we set) and less than ten
        assert now + 1 < expire_at < now + 10

        # Render a second time, should hit the cache but not for ``get_foo``
        expected = "foobar  foo 2  !!"
        assert self.render(t, {"multiplicator": 10}).strip() == expected
        assert self.get_name_called == 1  # Still 1
        assert self.get_foo_called == 2  # One more call to the non-cached part

    @override_settings(
        ADV_CACHE_RESOLVE_NAME=True,
    )
    def test_resolve_fragment_name(self):
        """Test passing the fragment name as a variable."""

        # Reset CacheTag config with default value (from the ``override_settings``)
        self.reload_config()

        expected = "foobar"

        t = """
            {% load adv_cache %}
            {% cache 1 fragment_name obj.pk obj.updated_at %}
                {{ obj.get_name }}
            {% endcache %}
        """

        # Render a first time, should miss the cache
        assert self.render(t, {"fragment_name": "test_cached_template"}).strip() == expected
        assert self.get_name_called == 1

        # Now the rendered template should be in cache
        key = self.get_template_key(
            "test_cached_template", vary_on=[self.obj["pk"], self.obj["updated_at"]]
        )
        assert key == "template.cache.test_cached_template.0cac9a03d5330dd78ddc9a0c16f01403"

        # But it should NOT be the exact content as adv_cache_tag adds a version
        assert caches["default"].get(key).strip() != expected

        # It should be the version from `adv_cache_tag`
        cache_expected = b"1::\n                foobar"
        assert caches["default"].get(key).strip() == cache_expected

        # Render a second time, should hit the cache
        assert self.render(t, {"fragment_name": "test_cached_template"}).strip() == expected
        assert self.get_name_called == 1  # Still 1

        # Using an undefined variable should fail
        t = """
            {% load adv_cache %}
            {% cache 1 undefined_fragment_name obj.pk obj.updated_at %}
                {{ obj.get_name }}
            {% endcache %}
        """

        with pytest.raises(template.VariableDoesNotExist) as raise_context:
            self.render(t, {"fragment_name": "test_cached_template"})
        assert "undefined_fragment_name" in str(raise_context)

    @override_settings(
        ADV_CACHE_RESOLVE_NAME=True,
    )
    def test_passing_fragment_name_as_string(self):
        """Test passing the fragment name as a variable."""

        # Reset CacheTag config with default value (from the ``override_settings``)
        self.reload_config()

        expected = "foobar"

        t = """
            {% load adv_cache %}
            {% cache 1 "test_cached_template" obj.pk obj.updated_at %}
                {{ obj.get_name }}
            {% endcache %}
        """

        # Render a first time, should miss the cache
        assert self.render(t).strip() == expected
        assert self.get_name_called == 1

        # Now the rendered template should be in cache
        key = self.get_template_key(
            "test_cached_template", vary_on=[self.obj["pk"], self.obj["updated_at"]]
        )
        assert key == "template.cache.test_cached_template.0cac9a03d5330dd78ddc9a0c16f01403"

        # But it should NOT be the exact content as adv_cache_tag adds a version
        assert caches["default"].get(key).strip() != expected

        # It should be the version from `adv_cache_tag`
        cache_expected = b"1::\n                foobar"
        assert caches["default"].get(key).strip() == cache_expected

        # Render a second time, should hit the cache
        assert self.render(t).strip() == expected
        assert self.get_name_called == 1  # Still 1

    def test_using_argument(self):
        """Test passing the cache backend to use with the `using=` arg to the templatetag."""

        expected = "foobar"

        t = """
            {% load adv_cache %}
            {% cache 1 test_cached_template obj.pk obj.updated_at using=foo %}
                {{ obj.get_name }}
            {% endcache %}
        """

        # Render a first time, should miss the cache
        assert self.render(t).strip() == expected
        assert self.get_name_called == 1

        # Now the rendered template should be in cache
        key = self.get_template_key(
            "test_cached_template", vary_on=[self.obj["pk"], self.obj["updated_at"]]
        )
        assert key == "template.cache.test_cached_template.0cac9a03d5330dd78ddc9a0c16f01403"

        # It should be in the cache
        cache_expected = b"1::\n                foobar"

        # But not in the ``default`` cache
        assert caches["default"].get(key) is None

        # But in the ``foo`` cache
        assert caches["foo"].get(key).strip() == cache_expected

        # Render a second time, should hit the cache
        assert self.render(t).strip() == expected
        assert self.get_name_called == 1  # Still 1

    @override_settings(
        ADV_CACHE_COMPRESS_SPACES=True,
    )
    def test_loading_libraries_in_nocache(self):
        """Test that needed libraries are loaded in the nocache block."""

        # Reset CacheTag config with default value (from the ``override_settings``)
        self.reload_config()

        expected = "foobar FoOoO   FOO 1FOO 1 FoOoO  !!"

        t = """
            {% load adv_cache other_tags %}
            {% cache 1 test_cached_template obj.pk obj.updated_at %}
                {{ obj.get_name }} {% insert_foo %}
                {% nocache %}
                    {% load other_filters %}
                    {{ obj.get_foo|double_upper }} {% insert_foo %}
                {% endnocache %}
                !!
            {% endcache %}
        """

        # Render a first time, should miss the cache
        assert self.render(t).strip() == expected
        assert self.get_name_called == 1
        assert self.get_foo_called == 1

        # Render a second time, should hit the cache but not for ``get_foo``
        expected = "foobar FoOoO   FOO 2FOO 2 FoOoO  !!"
        assert self.render(t).strip() == expected
        assert self.get_name_called == 1  # Still 1
        assert self.get_foo_called == 2  # One more call to the non-cached part

    def set_template_debug_true(self):
        templates_settings_copy = deepcopy(settings.TEMPLATES)
        for template_settings in templates_settings_copy:
            if template_settings["BACKEND"] == "django.template.backends.django.DjangoTemplates":
                template_settings.setdefault("OPTIONS", {})["debug"] = True
        return override_settings(TEMPLATES=templates_settings_copy)

    def test_failure_when_setting_cache(self):
        """Test that the template is correctly rendered even if the cache cannot be filled."""

        expected = "foobar"

        t = """
            {% load adv_cache_test %}
            {% cache_set_fail 1 test_cached_template obj.pk obj.updated_at %}
                {{ obj.get_name }}
            {% endcache_set_fail %}
        """

        # Render a first time, should still be rendered
        assert self.render(t).strip() == expected

        # Now the rendered template should NOT be in cache
        key = self.get_template_key(
            "test_cached_template",
            vary_on=[self.obj["pk"], self.obj["updated_at"]],
            prefix="template.cache_set_fail",
        )
        assert (
            key == "template.cache_set_fail.test_cached_template.0cac9a03d5330dd78ddc9a0c16f01403"
        )

        # But not in the ``default`` cache
        assert caches["default"].get(key) is None

        # It should raise if templates debug mode is activated
        with self.set_template_debug_true():
            with pytest.raises(ValueError) as raise_context:
                self.render(t)
            assert "boom set" in str(raise_context)

    def test_failure_when_getting_cache(self):
        """Test that the template is correctly rendered even if the cache cannot be read."""

        expected = "foobar"

        t = """
            {% load adv_cache_test %}
            {% cache_get_fail 1 test_cached_template obj.pk obj.updated_at %}
                {{ obj.get_name }}
            {% endcache_get_fail %}
        """

        # Render a first time, should still be rendered
        assert self.render(t).strip() == expected

        # Now the rendered template should be in cache
        key = self.get_template_key(
            "test_cached_template",
            vary_on=[self.obj["pk"], self.obj["updated_at"]],
            prefix="template.cache_get_fail",
        )
        assert (
            key == "template.cache_get_fail.test_cached_template.0cac9a03d5330dd78ddc9a0c16f01403"
        )

        # It should be in the cache
        cache_expected = b"1::\n                foobar"
        assert caches["default"].get(key).strip() == cache_expected

        # It should raise if templates debug mode is activated
        with self.set_template_debug_true():
            with pytest.raises(ValueError) as raise_context:
                self.render(t)
            assert "boom get" in str(raise_context)
