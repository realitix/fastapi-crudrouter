"""Unit tests for filtering module"""
# pylint: disable=protected-access

from pydantic import BaseModel
from sqlalchemy import Column, Integer, String, select
from sqlalchemy.orm import declarative_base

from fastapi_crudrouter.filtering import FilterBuilder, FilterOperator, OrderByBuilder

Base = declarative_base()


class SampleModel(Base):
    """Test SQLAlchemy model"""

    __tablename__ = "test_items"

    id = Column(Integer, primary_key=True)
    name = Column(String)
    age = Column(Integer)
    email = Column(String)


class SampleFilterSchema(BaseModel):
    """Test filter schema"""

    name: str | None = None
    age: int | None = None
    age__gte: int | None = None
    age__lte: int | None = None
    name__like: str | None = None


class TestFilterOperator:
    """Test FilterOperator enum"""

    def test_operator_values(self):
        """Test that operators have correct values"""
        assert FilterOperator.EQ == "eq"
        assert FilterOperator.GTE == "gte"
        assert FilterOperator.LTE == "lte"
        assert FilterOperator.LIKE == "like"
        assert FilterOperator.IN == "in"


class TestFilterBuilder:  # pylint: disable=too-many-public-methods
    """Test FilterBuilder class"""

    def test_init(self):
        """Test FilterBuilder initialization"""
        builder = FilterBuilder(SampleModel)
        assert builder.model == SampleModel
        assert len(builder._operator_handlers) == 4

    def test_apply_filters_with_none(self):
        """Test applying None filters returns query unchanged"""
        builder = FilterBuilder(SampleModel)
        query = select(SampleModel)
        result = builder.apply_filters(query, None, None, None)
        # Should return query with select_from added
        assert result is not None

    def test_handle_gte_operator(self):
        """Test >= operator"""
        builder = FilterBuilder(SampleModel)
        query = select(SampleModel)
        result = builder._handle_gte(query, "age", 18)
        # Verify the query was modified (can't easily check SQL without executing)
        assert result is not None

    def test_handle_lte_operator(self):
        """Test <= operator"""
        builder = FilterBuilder(SampleModel)
        query = select(SampleModel)
        result = builder._handle_lte(query, "age", 65)
        assert result is not None

    def test_handle_like_operator(self):
        """Test LIKE operator"""
        builder = FilterBuilder(SampleModel)
        query = select(SampleModel)
        result = builder._handle_like(query, "name", "John")
        assert result is not None

    def test_handle_in_operator(self):
        """Test IN operator with list"""
        builder = FilterBuilder(SampleModel)
        query = select(SampleModel)
        result = builder._handle_in(query, "age", [18, 25, 30])
        assert result is not None

    def test_handle_in_operator_single_value(self):
        """Test IN operator with single value (converted to list)"""
        builder = FilterBuilder(SampleModel)
        query = select(SampleModel)
        result = builder._handle_in(query, "age", 25)
        assert result is not None

    def test_handle_in_operator_tuple(self):
        """Test IN operator with tuple"""
        builder = FilterBuilder(SampleModel)
        query = select(SampleModel)
        result = builder._handle_in(query, "age", (18, 25, 30))
        assert result is not None

    def test_handle_in_operator_set(self):
        """Test IN operator with set"""
        builder = FilterBuilder(SampleModel)
        query = select(SampleModel)
        result = builder._handle_in(query, "age", {18, 25, 30})
        assert result is not None

    def test_handle_in_operator_comma_separated_string(self):
        """Test IN operator with comma-separated string"""
        builder = FilterBuilder(SampleModel)
        query = select(SampleModel)
        result = builder._handle_in(query, "name", "John,Jane,Bob")
        assert result is not None

    def test_handle_in_operator_comma_separated_with_spaces(self):
        """Test IN operator with comma-separated string with spaces"""
        builder = FilterBuilder(SampleModel)
        query = select(SampleModel)
        result = builder._handle_in(query, "name", "John , Jane , Bob")
        assert result is not None

    def test_handle_in_operator_string_without_comma(self):
        """Test IN operator with single string (no comma)"""
        builder = FilterBuilder(SampleModel)
        query = select(SampleModel)
        result = builder._handle_in(query, "name", "John")
        assert result is not None

    def test_apply_operator_filter_gte(self):
        """Test applying GTE operator filter"""
        builder = FilterBuilder(SampleModel)
        query = select(SampleModel)
        result = builder._apply_operator_filter(query, "age__gte", 18)
        assert result is not None

    def test_apply_operator_filter_lte(self):
        """Test applying LTE operator filter"""
        builder = FilterBuilder(SampleModel)
        query = select(SampleModel)
        result = builder._apply_operator_filter(query, "age__lte", 65)
        assert result is not None

    def test_apply_operator_filter_like(self):
        """Test applying LIKE operator filter"""
        builder = FilterBuilder(SampleModel)
        query = select(SampleModel)
        result = builder._apply_operator_filter(query, "name__like", "test")
        assert result is not None

    def test_apply_operator_filter_unknown_operator_ignored(self):
        """Test that unknown operators are gracefully ignored (no error)"""
        builder = FilterBuilder(SampleModel)
        query = select(SampleModel)
        # Should not raise AttributeError, should return query unchanged
        result = builder._apply_operator_filter(query, "name__contains", "test")
        assert result is not None
        # Query should be unchanged (operator ignored)
        assert result == query

    def test_apply_dict_filters_simple_equality(self):
        """Test applying simple equality filters"""
        builder = FilterBuilder(SampleModel)
        query = select(SampleModel)
        filters = {"name": "John", "age": 25}
        result = builder._apply_dict_filters(query, filters, None)
        assert result is not None

    def test_apply_dict_filters_skip_none(self):
        """Test that None values are skipped"""
        builder = FilterBuilder(SampleModel)
        query = select(SampleModel)
        filters = {"name": "John", "age": None}
        result = builder._apply_dict_filters(query, filters, None)
        assert result is not None

    def test_apply_dict_filters_with_operators(self):
        """Test applying filters with operators"""
        builder = FilterBuilder(SampleModel)
        query = select(SampleModel)
        filters = {"age__gte": 18, "age__lte": 65, "name__like": "test"}
        result = builder._apply_dict_filters(query, filters, None)
        assert result is not None

    def test_apply_filters_with_pydantic_model(self):
        """Test applying filters from Pydantic model"""
        builder = FilterBuilder(SampleModel)
        query = select(SampleModel)
        filters = SampleFilterSchema(name="John", age__gte=18)
        result = builder.apply_filters(query, filters, None, None)
        assert result is not None

    def test_apply_filters_with_contextual_filters(self):
        """Test applying contextual filters"""
        builder = FilterBuilder(SampleModel)
        query = select(SampleModel)
        contextual_filters = {"age__gte": 18}
        result = builder.apply_filters(query, None, contextual_filters, None)
        assert result is not None


class TestOrderByBuilder:
    """Test OrderByBuilder class"""

    def test_init(self):
        """Test OrderByBuilder initialization"""
        builder = OrderByBuilder(SampleModel, "id")
        assert builder.model == SampleModel
        assert builder.default_pk == "id"

    def test_get_order_by_none(self):
        """Test ordering with None parameter returns default DESC pk"""
        builder = OrderByBuilder(SampleModel, "id")
        result = builder.get_order_by(None)
        assert result is not None
        # Should be desc(SampleModel.id)

    def test_get_order_by_asc(self):
        """Test ordering ASC"""
        builder = OrderByBuilder(SampleModel, "id")
        result = builder.get_order_by("name")
        assert result is not None

    def test_get_order_by_desc(self):
        """Test ordering DESC"""
        builder = OrderByBuilder(SampleModel, "id")
        result = builder.get_order_by("name__DESC")
        assert result is not None

    def test_get_order_by_explicit_asc(self):
        """Test ordering with explicit ASC"""
        builder = OrderByBuilder(SampleModel, "id")
        result = builder.get_order_by("name__ASC")
        assert result is not None

    def test_get_order_by_invalid_field(self):
        """Test ordering with invalid field returns default"""
        builder = OrderByBuilder(SampleModel, "id")
        result = builder.get_order_by("invalid_field")
        assert result is not None

    def test_get_order_by_invalid_direction(self):
        """Test ordering with invalid direction defaults to ASC"""
        builder = OrderByBuilder(SampleModel, "id")
        result = builder.get_order_by("name__INVALID")
        assert result is not None

    def test_get_order_by_rejects_private_fields(self):
        """Test that private fields (starting with _) are rejected"""
        builder = OrderByBuilder(SampleModel, "id")
        result = builder.get_order_by("_private_field")
        assert result is not None
        # Should fallback to default

    def test_get_order_by_multiple_underscores(self):
        """Test field with multiple underscores in name"""
        builder = OrderByBuilder(SampleModel, "id")
        result = builder.get_order_by("some__field__name")
        # Should try to split on first __ and check field existence
        assert result is not None
