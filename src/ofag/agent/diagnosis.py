"""What a run that missed its target owes before its result is used."""

from pydantic import Field, model_validator

from ofag.core.schemas import StrictModel

__all__ = ["RuledOut", "Diagnosis"]

#: Below this a statement is a gesture. The same bar the decision record uses.
_MEANINGFUL = 24


class RuledOut(StrictModel):
    """One explanation, and the measurement that excluded it."""

    hypothesis: str = Field(min_length=_MEANINGFUL, max_length=200)
    #: What was run. "inverted both profiles flat", "swept lambda from 50 to 2",
    #: "attributed each failed reading to its four electrodes".
    measurement: str = Field(min_length=_MEANINGFUL, max_length=300)
    #: What the measurement gave, in numbers where there are numbers.
    result: str = Field(min_length=_MEANINGFUL, max_length=400)


class Diagnosis(StrictModel):
    """Why a run missed its target, as far as anyone got."""

    #: What the run reports and what it was held to.
    misfit: float = Field(gt=0)
    target: float = Field(gt=0)
    #: Whether the misfit is spread or concentrated, and where if it is concentrated.
    where: str = Field(min_length=_MEANINGFUL, max_length=600)
    #: Explanations tested and excluded.
    ruled_out: tuple[RuledOut, ...] = ()
    #: What the misfit is left as. May be an admission.
    remaining: str = Field(min_length=_MEANINGFUL, max_length=600)

    @property
    def fitted(self) -> bool:
        return self.misfit <= self.target

    @model_validator(mode="after")
    def a_miss_has_to_have_been_looked_into(self) -> "Diagnosis":
        if self.fitted:
            return self
        if not self.ruled_out:
            raise ValueError(
                f"a misfit of {self.misfit:.3f} against a bar of {self.target:.3f} with nothing "
                "ruled out is a number, not a diagnosis: name at least one explanation and the "
                "measurement that excluded it"
            )
        return self

    @property
    def summary(self) -> str:
        """One line for a report, naming what was excluded and what is left."""
        excluded = "; ".join(entry.hypothesis for entry in self.ruled_out)
        return (
            f"chi squared {self.misfit:.3f} against {self.target:.0f}. {self.where} "
            f"Ruled out: {excluded}. What is left: {self.remaining}"
        )
