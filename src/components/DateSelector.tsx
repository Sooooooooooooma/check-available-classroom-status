import type { Dispatch, SetStateAction } from "react"

type Props = {
  selectedDate: string;
  setSelectedDate: Dispatch<SetStateAction<string>>;
};

function DateSelecter({ selectedDate, setSelectedDate }: Props) {
  return (
    <>
      <div>DateSelecter</div>
      <div>{selectedDate}</div>
    </>
  )
}

export default DateSelecter