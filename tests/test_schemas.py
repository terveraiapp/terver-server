from app.models.schemas import CategoryFinding, AnalysisResult, ChatRequest
import pytest
from pydantic import ValidationError


def test_category_finding_valid():
    f = CategoryFinding(name="Ownership Integrity", status="PASS", findings=["Chain is complete"])
    assert f.status == "PASS"
    assert f.name == "Ownership Integrity"
    assert f.findings == ["Chain is complete"]


def test_category_finding_invalid_status():
    with pytest.raises(ValidationError):
        CategoryFinding(name="X", status="UNKNOWN", findings=[])


def test_category_finding_valid_statuses():
    for status in ["PASS", "WARN", "FAIL"]:
        f = CategoryFinding(name="Test", status=status, findings=[])
        assert f.status == status


def test_analysis_result_risk_score():
    result = AnalysisResult(
        risk_score="HIGH",
        overall_score=82,
        categories=[],
        summary="High risk document."
    )
    assert result.overall_score == 82
    assert result.risk_score == "HIGH"


def test_analysis_result_valid_risk_scores():
    for risk in ["LOW", "MEDIUM", "HIGH"]:
        result = AnalysisResult(
            risk_score=risk,
            overall_score=50,
            categories=[],
            summary="Test"
        )
        assert result.risk_score == risk


def test_analysis_result_invalid_risk_score():
    with pytest.raises(ValidationError):
        AnalysisResult(
            risk_score="CRITICAL",
            overall_score=82,
            categories=[],
            summary="High risk document."
        )


def test_analysis_result_with_categories():
    categories = [
        CategoryFinding(name="Ownership Integrity", status="PASS", findings=["Chain is complete"]),
        CategoryFinding(name="Document Authenticity", status="WARN", findings=["Signature missing"]),
    ]
    result = AnalysisResult(
        risk_score="MEDIUM",
        overall_score=65,
        categories=categories,
        summary="Mixed findings."
    )
    assert len(result.categories) == 2
    assert result.categories[0].status == "PASS"
    assert result.categories[1].status == "WARN"


def test_chat_request_required_fields():
    req = ChatRequest(message="Who owns this land?")
    assert req.message == "Who owns this land?"
    assert req.document_context == ""


def test_chat_request_with_context():
    req = ChatRequest(
        message="Who owns this land?",
        document_context="Land deed from 2020"
    )
    assert req.document_context == "Land deed from 2020"


def test_chat_request_missing_required_field():
    with pytest.raises(ValidationError):
        ChatRequest()


def test_session_created():
    from app.models.schemas import SessionCreated
    session = SessionCreated(
        session_id="550e8400-e29b-41d4-a716-446655440000",
        document_name="deed.pdf"
    )
    assert session.session_id == "550e8400-e29b-41d4-a716-446655440000"
    assert session.document_name == "deed.pdf"
