"""Tests for job_api_aggregator schema dataclasses and TypedDict.

Covers PluginField, PluginInfo, SearchParams, and the JobRecord TypedDict
structural expectations.
"""

from job_api_aggregator.schema import (
    JobRecord,
    PluginField,
    PluginInfo,
    SearchParams,
)


class TestPluginField:
    """Tests for the PluginField frozen dataclass."""

    def test_required_fields_only(self) -> None:
        """PluginField can be constructed with only required fields."""
        field = PluginField(name="app_id", label="App ID", type="password")
        assert field.name == "app_id"
        assert field.label == "App ID"
        assert field.type == "password"

    def test_default_required_is_false(self) -> None:
        """required defaults to False when not specified."""
        field = PluginField(name="app_id", label="App ID", type="text")
        assert field.required is False

    def test_default_help_text_is_none(self) -> None:
        """help_text defaults to None when not specified."""
        field = PluginField(name="app_id", label="App ID", type="text")
        assert field.help_text is None

    def test_all_fields(self) -> None:
        """PluginField stores all provided attribute values correctly."""
        field = PluginField(
            name="app_key",
            label="App Key",
            type="password",
            required=True,
            help_text="Found in your Adzuna developer console.",
        )
        assert field.name == "app_key"
        assert field.label == "App Key"
        assert field.type == "password"
        assert field.required is True
        assert field.help_text == "Found in your Adzuna developer console."

    def test_is_frozen(self) -> None:
        """PluginField instances are immutable."""
        import dataclasses

        field = PluginField(name="x", label="X", type="text")
        assert dataclasses.is_dataclass(field)
        with __import__("pytest").raises((dataclasses.FrozenInstanceError, TypeError)):
            field.name = "y"  # type: ignore[misc]

    def test_all_valid_types(self) -> None:
        """All five declared field types are constructable."""
        valid_types: list[str] = ["text", "password", "email", "url", "number"]
        for ftype in valid_types:
            # Iterating over a list[str] loses the Literal type; cast to satisfy mypy.
            field = PluginField(name="f", label="F", type=ftype)  # type: ignore[arg-type]
            assert field.type == ftype


class TestPluginInfo:
    """Tests for the PluginInfo frozen dataclass."""

    def _make_info(
        self,
        fields: tuple[PluginField, ...] = (),
    ) -> PluginInfo:
        """Return a minimal valid PluginInfo for testing."""
        return PluginInfo(
            key="dummy",
            display_name="Dummy",
            description="A dummy source.",
            home_url="https://dummy.example.com",
            geo_scope="global",
            accepts_query="always",
            accepts_location=True,
            accepts_country=False,
            rate_limit_notes="None.",
            required_search_fields=(),
            fields=fields,
        )

    def test_basic_construction(self) -> None:
        """PluginInfo can be created with all fields populated."""
        info = self._make_info()
        assert info.key == "dummy"
        assert info.display_name == "Dummy"

    def test_requires_credentials_false_when_no_required_fields(self) -> None:
        """requires_credentials is False when no field is marked required."""
        fields = (
            PluginField(name="optional_key", label="Optional Key", type="text", required=False),
        )
        info = self._make_info(fields=fields)
        assert info.requires_credentials is False

    def test_requires_credentials_true_when_any_field_required(self) -> None:
        """requires_credentials is True when at least one field is required."""
        fields = (
            PluginField(name="app_id", label="App ID", type="password", required=True),
            PluginField(name="app_key", label="App Key", type="password", required=False),
        )
        info = self._make_info(fields=fields)
        assert info.requires_credentials is True

    def test_requires_credentials_true_when_all_fields_required(self) -> None:
        """requires_credentials is True when all fields are required."""
        fields = (PluginField(name="api_key", label="API Key", type="password", required=True),)
        info = self._make_info(fields=fields)
        assert info.requires_credentials is True

    def test_requires_credentials_false_when_no_fields(self) -> None:
        """requires_credentials is False when there are no fields."""
        info = self._make_info(fields=())
        assert info.requires_credentials is False

    def test_required_search_fields_stored(self) -> None:
        """required_search_fields tuple is preserved."""
        info = PluginInfo(
            key="adzuna",
            display_name="Adzuna",
            description="Global aggregator.",
            home_url="https://www.adzuna.com",
            geo_scope="global-by-country",
            accepts_query="always",
            accepts_location=True,
            accepts_country=True,
            rate_limit_notes="1 req/sec.",
            required_search_fields=("country", "what"),
            fields=(),
        )
        assert info.required_search_fields == ("country", "what")


class TestSearchParams:
    """Tests for the SearchParams frozen dataclass."""

    def test_all_defaults(self) -> None:
        """SearchParams can be constructed with no arguments."""
        params = SearchParams()
        assert params.query is None
        assert params.location is None
        assert params.country is None
        assert params.hours == 168
        assert params.max_pages is None

    def test_custom_values(self) -> None:
        """All SearchParams fields can be set explicitly."""
        params = SearchParams(
            query="python developer",
            location="Atlanta, GA",
            country="us",
            hours=24,
            max_pages=3,
        )
        assert params.query == "python developer"
        assert params.location == "Atlanta, GA"
        assert params.country == "us"
        assert params.hours == 24
        assert params.max_pages == 3

    def test_is_frozen(self) -> None:
        """SearchParams instances are immutable."""
        import dataclasses

        params = SearchParams()
        with __import__("pytest").raises((dataclasses.FrozenInstanceError, TypeError)):
            params.hours = 48  # type: ignore[misc]


class TestJobRecord:
    """Tests for the JobRecord TypedDict structural contract.

    JobRecord is a TypedDict, not a runtime-enforced class.  These tests
    confirm that the dict shape assembles without error and that field
    names exist on the type (via presence in annotations).
    """

    def test_minimal_required_record_is_valid_dict(self) -> None:
        """A record with only required fields is a valid plain dict."""
        record: JobRecord = {
            "source": "dummy",
            "source_id": "abc123",
            "description_source": "snippet",
            "title": "Software Engineer",
            "url": "https://example.com/job/1",
            "posted_at": "2026-04-23T00:00:00Z",
            "description": "A great job.",
        }
        assert record["source"] == "dummy"
        assert record["source_id"] == "abc123"
        assert record["description_source"] == "snippet"

    def test_full_record_with_optional_fields(self) -> None:
        """A fully populated record (all optional fields) is a valid dict."""
        record: JobRecord = {
            "source": "adzuna",
            "source_id": "xyz",
            "description_source": "full",
            "title": "Backend Engineer",
            "url": "https://adzuna.com/job/xyz",
            "posted_at": None,
            "description": "Full description here.",
            "company": "Acme Corp",
            "location": "London, UK",
            "salary_min": 60000.0,
            "salary_max": 90000.0,
            "salary_currency": "GBP",
            "salary_period": "annual",
            "contract_type": "permanent",
            "contract_time": "full_time",
            "remote_eligible": True,
            "extra": {"adzuna_category": "IT Jobs"},
        }
        assert record["company"] == "Acme Corp"
        assert record["salary_period"] == "annual"
        assert record["extra"] == {"adzuna_category": "IT Jobs"}

    def test_record_accepts_none_for_optional_fields(self) -> None:
        """Optional fields may be explicitly set to None."""
        record: JobRecord = {
            "source": "remoteok",
            "source_id": "ro-1",
            "description_source": "none",
            "title": "",
            "url": "",
            "posted_at": None,
            "description": "",
            "company": None,
            "location": None,
            "salary_min": None,
            "salary_max": None,
            "salary_currency": None,
            "salary_period": None,
            "contract_type": None,
            "contract_time": None,
            "remote_eligible": None,
            "extra": None,
        }
        assert record["salary_period"] is None
        assert record["extra"] is None

    def test_required_identity_fields_exist_in_annotations(self) -> None:
        """JobRecord's __annotations__ contains the three identity fields."""
        annotations = {**JobRecord.__annotations__}
        for field in ("source", "source_id", "description_source"):
            assert field in annotations, f"Missing identity field: {field}"

    def test_required_always_present_fields_exist_in_annotations(self) -> None:
        """JobRecord's annotations contain the four always-present fields."""
        annotations = {**JobRecord.__annotations__}
        for field in ("title", "url", "posted_at", "description"):
            assert field in annotations, f"Missing always-present field: {field}"

    def test_optional_fields_exist_in_annotations(self) -> None:
        """JobRecord's annotations contain all optional fields."""
        annotations = {**JobRecord.__annotations__}
        optional_fields = (
            "company",
            "location",
            "salary_min",
            "salary_max",
            "salary_currency",
            "salary_period",
            "contract_type",
            "contract_time",
            "remote_eligible",
            "extra",
        )
        for field in optional_fields:
            assert field in annotations, f"Missing optional field: {field}"
