"""Abstract base class for job-aggregator source plugins.

Plugin authors subclass :class:`JobSource`, declare the required class-level
metadata attributes, and implement the three abstract methods.
:meth:`JobSource.__init_subclass__` enforces attribute presence at
class-creation time so missing metadata is caught at import, not at runtime.

Example::

    from collections.abc import Iterator
    from typing import Any

    from job_aggregator.base import JobSource
    from job_aggregator.schema import SearchParams


    class MySource(JobSource):
        SOURCE = "mysource"
        DISPLAY_NAME = "My Source"
        DESCRIPTION = "Fetches jobs from My Source API."
        HOME_URL = "https://mysource.example.com"
        GEO_SCOPE = "global"
        ACCEPTS_QUERY = "always"
        ACCEPTS_LOCATION = True
        ACCEPTS_COUNTRY = True
        RATE_LIMIT_NOTES = "No published limit."
        REQUIRED_SEARCH_FIELDS: tuple[str, ...] = ()

        @classmethod
        def settings_schema(cls) -> dict[str, Any]:
            return {
                "api_key": {
                    "label": "API Key",
                    "type": "password",
                    "required": True,
                }
            }

        def __init__(
            self,
            *,
            credentials: dict[str, Any] | None = None,
            search: SearchParams | None = None,
        ) -> None:
            super().__init__(credentials=credentials, search=search)
            creds = credentials or {}
            # validate credentials here …

        def pages(self) -> Iterator[list[dict[str, Any]]]:
            ...

        def normalise(self, raw: dict[str, Any]) -> dict[str, Any]:
            ...
"""

from __future__ import annotations

import abc
import inspect
from collections.abc import Iterator
from typing import TYPE_CHECKING, Any, ClassVar, Literal

if TYPE_CHECKING:
    from job_aggregator.schema import SearchParams

# ---------------------------------------------------------------------------
# Required class-level attribute names — enforced by __init_subclass__
# ---------------------------------------------------------------------------

_REQUIRED_CLASS_ATTRS: tuple[str, ...] = (
    "SOURCE",
    "DISPLAY_NAME",
    "DESCRIPTION",
    "HOME_URL",
    "GEO_SCOPE",
    "ACCEPTS_QUERY",
    "ACCEPTS_LOCATION",
    "ACCEPTS_COUNTRY",
    "RATE_LIMIT_NOTES",
)


# ---------------------------------------------------------------------------
# JobSource ABC
# ---------------------------------------------------------------------------


class JobSource(abc.ABC):
    """Abstract base class for all job-aggregator source plugins.

    Every plugin must subclass ``JobSource``, declare the required
    class-level metadata attributes, and implement the three abstract
    methods.  The ``__init_subclass__`` hook enforces attribute presence
    at class-creation time; missing attributes raise :exc:`TypeError`
    immediately on import rather than producing confusing
    :exc:`AttributeError` failures at runtime.

    Class-level attributes (must be declared on every concrete subclass):

    Attributes:
        SOURCE: Unique machine-readable plugin key used as the dict key
            in credentials files and as the ``source`` field in output
            records (e.g. ``"adzuna"``).
        DISPLAY_NAME: Human-readable plugin name shown in UIs
            (e.g. ``"Adzuna"``).
        DESCRIPTION: Short description of the job source.
        HOME_URL: URL for the source's public homepage.
        GEO_SCOPE: Geographic coverage of the source.  One of:
            ``"global"``, ``"global-by-country"``, ``"remote-only"``,
            ``"federal-us"``, ``"regional"``, ``"unknown"``.
        ACCEPTS_QUERY: How the source handles free-text queries.  One of:
            ``"always"`` (query is sent to the API),
            ``"partial"`` (query is partially supported or best-effort),
            ``"never"`` (source does not accept a query parameter).
        ACCEPTS_LOCATION: ``True`` if the source accepts a location
            filter in its API.
        ACCEPTS_COUNTRY: ``True`` if the source accepts a country code
            filter in its API.
        RATE_LIMIT_NOTES: Human-readable rate-limit information for the
            source (e.g. ``"1 req/sec, 250/day on free tier"``).
        REQUIRED_SEARCH_FIELDS: Tuple of :class:`~job_aggregator.schema.SearchParams`
            field names that must be non-``None`` for the plugin to run
            successfully (e.g. ``("country",)``).  Defaults to ``()``.
    """

    SOURCE: ClassVar[str]
    DISPLAY_NAME: ClassVar[str]
    DESCRIPTION: ClassVar[str]
    HOME_URL: ClassVar[str]
    GEO_SCOPE: ClassVar[
        Literal["global", "global-by-country", "remote-only", "federal-us", "regional", "unknown"]
    ]
    ACCEPTS_QUERY: ClassVar[Literal["always", "partial", "never"]]
    ACCEPTS_LOCATION: ClassVar[bool]
    ACCEPTS_COUNTRY: ClassVar[bool]
    RATE_LIMIT_NOTES: ClassVar[str]
    REQUIRED_SEARCH_FIELDS: ClassVar[tuple[str, ...]] = ()

    # ------------------------------------------------------------------
    # Canonical constructor
    # ------------------------------------------------------------------

    def __init__(
        self,
        *,
        credentials: dict[str, Any] | None = None,
        search: SearchParams | None = None,
    ) -> None:
        """Store credentials and search parameters on the instance.

        Concrete subclasses **must** call ``super().__init__()`` with the
        same keyword arguments before performing their own credential
        validation.  The base implementation simply stores the raw values;
        validation is the subclass's responsibility.

        Args:
            credentials: Credentials dict for the plugin (may be
                ``None`` for no-auth plugins).
            search: :class:`~job_aggregator.schema.SearchParams` instance
                carrying the user's search query, location, country,
                hours, and page-count preferences.  May be ``None`` when
                no search parameters are provided.
        """
        self._credentials: dict[str, Any] = credentials or {}
        self._search: SearchParams | None = search

    # ------------------------------------------------------------------
    # Subclass enforcement hook
    # ------------------------------------------------------------------

    def __init_subclass__(cls, **kwargs: Any) -> None:
        """Enforce required class-level attributes on concrete subclasses.

        Called automatically by Python for every class that directly or
        indirectly inherits from :class:`JobSource`.  If the subclass is
        still abstract (i.e. it has unimplemented abstract methods),
        enforcement is skipped so intermediate base classes can omit the
        attributes without raising.

        Args:
            **kwargs: Forwarded to :func:`super().__init_subclass__`.

        Raises:
            TypeError: If the concrete subclass does not declare one or
                more of the required class-level attributes listed in
                :data:`_REQUIRED_CLASS_ATTRS`.
        """
        super().__init_subclass__(**kwargs)

        # Skip enforcement for abstract intermediate classes.
        # inspect.isabstract checks for non-empty __abstractmethods__
        # which is set by ABCMeta before __init_subclass__ is called.
        if inspect.isabstract(cls):
            return

        missing = [attr for attr in _REQUIRED_CLASS_ATTRS if not hasattr(cls, attr)]
        if missing:
            raise TypeError(
                f"Concrete JobSource subclass {cls.__name__!r} must declare "
                f"the following class-level attributes: "
                f"{', '.join(missing)}."
            )

    # ------------------------------------------------------------------
    # Abstract methods (must be implemented by every concrete subclass)
    # ------------------------------------------------------------------

    @classmethod
    @abc.abstractmethod
    def settings_schema(cls) -> dict[str, Any]:
        """Return the field definitions used to build :class:`~job_aggregator.schema.PluginInfo`.

        Declared as a ``@classmethod`` so callers can introspect a plugin's
        schema without constructing an instance.  Concrete subclasses must
        decorate their override with ``@classmethod`` as well.

        Each key in the returned dict is a credential / configuration
        field name; the value is a dict describing the field with the
        following keys:

        - ``"label"`` (:class:`str`) — human-readable field label.
        - ``"type"`` (:class:`str`) — one of ``"text"``, ``"password"``,
          ``"email"``, ``"url"``, ``"number"``.
        - ``"required"`` (:class:`bool`, optional) — whether the field
          must be present; defaults to ``False``.
        - ``"help_text"`` (:class:`str`, optional) — explanatory text.

        Returns:
            A dict mapping field name to field definition.  Return an
            empty dict for plugins that require no credentials.
        """
        ...

    @abc.abstractmethod
    def pages(self) -> Iterator[list[dict[str, Any]]]:
        """Yield pages of raw job listings from the source API.

        Each yielded page is a list of raw dicts as returned by the
        source API.  The caller passes each raw dict to
        :meth:`normalise`.  Search parameters (query, location,
        country, hours, max_pages) are accepted by the constructor and
        stored as instance attributes; ``pages()`` takes no arguments.

        Yields:
            A list of raw API dicts for each page of results.  Yielding
            an empty list is valid and signals "no more results".
        """
        ...

    @abc.abstractmethod
    def normalise(self, raw: dict[str, Any]) -> dict[str, Any]:
        """Map a raw source-API dict to the package's normalised record shape.

        The returned dict should conform to the :class:`~job_aggregator.schema.JobRecord`
        TypedDict contract.  In particular it must include the identity
        fields ``source``, ``source_id``, and ``description_source``, and
        the always-present fields ``title``, ``url``, ``posted_at``, and
        ``description``.

        Args:
            raw: A single raw listing dict as yielded by :meth:`pages`.

        Returns:
            A normalised dict ready for output as a :class:`~job_aggregator.schema.JobRecord`.
        """
        ...
